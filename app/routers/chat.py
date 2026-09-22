import asyncio
import logging
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from app.core.dependencies import get_current_user_id
from app.core.errors import APIError, api_error_handler
from app.schemas.chat import ChatLogListResponse, ChatRequest, ChatResponse, ErrorResponse
from app.services import ai_service, chat as chat_service

logger = logging.getLogger(__name__)


class ChatRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                return await api_error_handler(request, APIError(
                    422, "INVALID_INPUT", "요청 내용을 확인해 주세요. 질문은 공백만으로 구성할 수 없으며 최대 5,000자입니다.",
                ))

        return handler


router = APIRouter(
    prefix="/api", tags=["chat"], route_class=ChatRoute,
    responses={code: {"model": ErrorResponse} for code in (401, 422, 429, 502, 503, 504)},
)


@router.post("/chat", response_model=ChatResponse)
async def send_chat(data: ChatRequest, user_id: str = Depends(get_current_user_id)):
    request_id = uuid4().hex
    started = time.perf_counter()
    try:
        question = ai_service.validate_question(data.question)
    except ai_service.QuestionValidationError as exc:
        raise APIError(422, exc.error_code, exc.message, request_id) from None
    # 대화방(conversations) 테이블이 아직 없으므로 사용자 기준 최근 N턴을 문맥으로 쓴다.
    # DB 조회는 동기라 스레드풀로 넘긴다. 실패해도 빈 리스트가 와서 답변은 진행된다.
    history = await run_in_threadpool(chat_service.get_recent_history, user_id)
    try:
        result = await asyncio.wait_for(
            ai_service.generate_answer(
                question, history, user_id=user_id, request_id=request_id
            ),
            timeout=ai_service.AI_TOTAL_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        timed_out = isinstance(exc, TimeoutError)
        code = ai_service.ErrorCode.TIMEOUT if timed_out else ai_service.ErrorCode.UNKNOWN
        logger.error("chat_ai_failed request_id=%s kind=%s", request_id, type(exc).__name__)
        result = ai_service.AIResult(
            status="timeout" if timed_out else "error", request_id=request_id,
            model=ai_service.AI_MODEL, latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=code, user_message=ai_service.USER_MESSAGES[code],
        )

    if result.is_success and (not result.answer or not result.answer.strip()):
        result.status = "error"
        result.error_code = ai_service.ErrorCode.EMPTY_RESPONSE
        result.user_message = ai_service.USER_MESSAGES[result.error_code]
    elif result.is_success and len(result.answer) > 5000:
        result.status = "error"
        result.error_code = "AI_ANSWER_TOO_LONG"
        result.user_message = "답변이 5,000자를 초과했습니다. 더 짧은 답변을 요청해 주세요."
    if not result.is_success:
        result.answer = None

    created_at = await run_in_threadpool(chat_service.save_result, user_id, question, result)
    if not result.is_success:
        status_code = {
            ai_service.ErrorCode.TIMEOUT: 504,
            ai_service.ErrorCode.RATE_LIMIT: 429,
            ai_service.ErrorCode.BLOCKED: 422,
        }.get(result.error_code, 502)
        raise APIError(
            status_code, result.error_code or ai_service.ErrorCode.UNKNOWN,
            result.user_message or "답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            result.request_id,
        )
    return ChatResponse(answer=result.answer, request_id=result.request_id, created_at=created_at)


@router.get("/me/chats", response_model=ChatLogListResponse)
def get_my_chats(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    return chat_service.list_chats(user_id, limit, offset)
