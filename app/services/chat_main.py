import asyncio
import time

from uuid                   import uuid4
from datetime               import timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core               import config
from app.core.errors        import APIError, ErrorCode, USER_MESSAGES, AI_ERROR_STATUS
from app.core.logging       import log_event, request_id_context
from app.schemas.chat       import ChatRequest, AIResult
from app.services           import chat_db, AI_connect


async def chat(data: ChatRequest, user_id: str, db: AsyncSession):
    question   = validate_question(data)
    request_id = request_id_context.get() or uuid4().hex
    history    = await chat_db.get_history(user_id, db)
    started    = time.perf_counter()

    try:
        result = await asyncio.wait_for(
            AI_connect.generate_answer(
                question   = question,
                history    = history,
                user_id    = user_id,
                request_id = request_id,
            ),
            timeout = config.AI_TOTAL_TIMEOUT_SECONDS,
        )
        if not isinstance(result, AIResult):
            raise TypeError("Invalid AI result")
    except Exception as exc:
        log_event("chat_ai_failed", exc=exc, request_id=request_id)
        code   = ErrorCode.TIMEOUT if isinstance(exc, TimeoutError) else ErrorCode.UNKNOWN
        result = AIResult(
            status       = "timeout" if code == ErrorCode.TIMEOUT else "error",
            request_id   = request_id,
            model        = config.AI_MODEL,
            latency_ms   = int((time.perf_counter() - started) * 1000),
            error_code   = code,
            user_message = USER_MESSAGES[code],
        )

    result.request_id = request_id
    validate_result(result)

    created_at = await chat_db.save_result(
        db       = db,
        user_id  = user_id,
        question = question,
        result   = result
    )

    if result.status != "success":
        raise APIError(
            AI_ERROR_STATUS.get(result.error_code, 502),
            result.error_code,
            result.user_message,
            result.request_id,
        )

    return {
        "answer"     : result.answer,
        "request_id" : result.request_id,
        "created_at" : created_at.isoformat().replace("+00:00", "Z"),
    }


def validate_question(data: ChatRequest) -> str:
    question = data.question.strip()
    if not question:
        raise APIError(422, ErrorCode.INVALID_INPUT, "질문을 입력해 주세요.")

    limit = min(config.MAX_QUESTION_LENGTH, 5000)
    if len(question) > limit:
        raise APIError(422, ErrorCode.INVALID_INPUT, f"질문은 {limit:,}자 이내로 입력해 주세요.")
    return question


def validate_result(result: AIResult):
    if result.status == "success":
        if not isinstance(result.answer, str) or not result.answer.strip():
            result.error_code = ErrorCode.EMPTY_RESPONSE
        elif len(result.answer) > 5000:
            result.error_code = ErrorCode.ANSWER_TOO_LONG
        else:
            result.error_code   = None
            result.user_message = None
            return
    elif result.status not in ("error", "timeout"):
        result.error_code = ErrorCode.UNKNOWN

    if not result.error_code:
        if result.status == "timeout":
            result.error_code = ErrorCode.TIMEOUT
        else:
            result.error_code = ErrorCode.UNKNOWN
    result.status       = "timeout" if result.error_code == ErrorCode.TIMEOUT else "error"
    result.answer       = None
    result.user_message = USER_MESSAGES.get(result.error_code, USER_MESSAGES[ErrorCode.UNKNOWN])


async def get_my_chat(user_id: str, db: AsyncSession):
    rows = await chat_db.get_list_chat(user_id, db)
    return [
        {
            "id"         : row.id,
            "question"   : row.question,
            "answer"     : row.answer,
            "status"     : row.status,
            "created_at" : row.created_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        for row in rows
    ]
