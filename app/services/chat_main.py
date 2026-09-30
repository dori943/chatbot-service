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


# 채팅 요청 처리의 핵심 비즈니스 로직(파이프라인)을 수행하는 함수
async def chat(data: ChatRequest, user_id: str, db: AsyncSession):
    # 1. 요청 데이터(room_id, room_name, question) 2차 비즈니스 유효성 검증
    room_id    = validate_room_id(data)
    room_name  = validate_room_name(data)
    question   = validate_question(data)
    # 2. 요청 추적(Tracing)을 위한 고유 식별자(UUID) 할당
    request_id = request_id_context.get() or uuid4().hex
    # 3. 대화 문맥(Context) 유지를 위해 DB에서 해당 사용자의 방별 이전 대화 이력 조회
    history    = await chat_db.get_history(user_id, room_id, db)
    # 4. AI 응답 지연 시간(Latency) 측정을 위한 타이머 시작
    started    = time.perf_counter()

    try:
        # asyncio.wait_for는 내부의 AI_connect.generate_answer() 코루틴을 실행하고,
        # 해당 함수가 성공 시 return한 AIResult(status="success") 객체를 그대로 전달받아 result 변수에 할당함
        # 지정된 timeout(제한 시간) 초과 시 TimeoutError를 발생시켜 아래 except 블록으로 제어를 넘김
        result = await asyncio.wait_for(
            # 실제 외부 LLM API와 통신하여 질문에 대한 답변을 생성하는 코루틴 호출
            AI_connect.generate_answer(
                # 사용자가 현재 입력한 질문 텍스트
                question   = question,
                # 대화 문맥(Context) 유지를 위한 이전 대화 목록
                history    = history,
                # 속도 제한(Rate Limit) 및 사용자 식별용 ID
                user_id    = user_id,
                # 요청 상관관계(Correlation ID) 추적용 식별자
                request_id = request_id,
            ),
            # 설정 파일에 정의된 초 단위 제한 시간 (초과 시 asyncio.TimeoutError 발생)
            timeout = config.AI_TOTAL_TIMEOUT_SECONDS,
        )
        # AI 모듈이 반환한 데이터가 규격 클래스(AIResult) 형태인지 런타임 타입 검사
        if not isinstance(result, AIResult):
            # 규격에 맞지 않으면 의도적으로 예외를 발생시켜 except 블록으로 전달
            raise TypeError("Invalid AI result")
    except Exception as exc:
        # AI 호출 실패 또는 타임아웃 발생 시 장애 분석용 이벤트 로그 기록
        log_event("chat_ai_failed", exc=exc, request_id=request_id)
        # 발생한 예외가 타임아웃인지 일반 에러인지 구분하여 에러 코드 부여
        code   = ErrorCode.TIMEOUT if isinstance(exc, TimeoutError) else ErrorCode.UNKNOWN
        # 시스템 장애 시에도 비정상 종료를 막기 위해 에러 정보를 담은 대체(Fallback) 객체 수동 생성
        result = AIResult(
            # 에러 상태 분류 (timeout 또는 error)
            status       = "timeout" if code == ErrorCode.TIMEOUT else "error",
            # 요청 상관관계 추적용 식별자 유지
            request_id   = request_id,
            # 사용된 AI 모델명
            model        = config.AI_MODEL,
            # 실패까지 소요된 시간 (밀리초 단위)
            latency_ms   = int((time.perf_counter() - started) * 1000),
            # 시스템 내부 에러 분류 코드
            error_code   = code,
            # 사용자 화면에 노출할 친절한 안내 메시지
            user_message = USER_MESSAGES[code],
        )

    # 응답 객체에 요청 식별자(UUID)를 명시적으로 재할당하여 추적성 보장
    result.request_id = request_id
    # 반환 객체의 필수 속성 존재 여부 및 데이터 무결성 검증
    validate_result(result)

    # 성공/실패 여부와 관계없이 사용자의 질문과 처리 결과를 데이터베이스 테이블에 영속화(저장)
    created_at = await chat_db.save_result(
        # 의존성 주입으로 전달받은 비동기 DB 세션
        db        = db,
        # 요청을 보낸 사용자 ID
        user_id   = user_id,
        # 대화방 ID
        room_id   = room_id,
        # 대화방 이름
        room_name = room_name,
        # 사용자 질문 원문
        question  = question,
        # AI 결과(성공 답변 또는 Fallback 에러 객체)
        result    = result,
    )

    # result.status 상태 판별:
    # 1) 정상 성공 시: AI_connect.py에서 외부 AI 호출 성공 후 return한 AIResult의 status="success"를 유지함
    # 2) 실패/타임아웃 시: 위 except 블록에서 조립한 Fallback AIResult의 status("timeout" 또는 "error")가 들어있음
    # 따라서 status가 "success"가 아닐 경우 클라이언트로 전파할 APIError 예외를 발생시킴
    if result.status != "success":
        # FastAPI 전역 예외 처리기로 위임할 APIError 예외 발생 (적절한 HTTP Status Code 매핑)
        raise APIError(
            # 에러 코드에 대응하는 HTTP 상태 코드 (기본 502 Bad Gateway)
            AI_ERROR_STATUS.get(result.error_code, 502),
            # 내부 정의 에러 코드
            result.error_code,
            # 사용자에게 전달할 에러 안내 문구
            result.user_message,
            # 추적용 요청 식별자
            result.request_id,
        )

    # 모든 공정이 정상 완료되었을 때 프론트엔드로 전달할 최종 JSON 응답 딕셔너리
    return {
        # 대화방 ID
        "room_id"    : room_id,
        # 대화방 이름
        "room_name"  : room_name,
        # AI가 생성한 최종 답변 텍스트
        "answer"     : result.answer,
        # 요청 추적용 고유 ID
        "request_id" : result.request_id,
        # 프론트엔드 파싱을 위한 UTC ISO-8601 시각 문자열
        "created_at" : created_at.isoformat().replace("+00:00", "Z"),
    }


# 2차 비즈니스 검증: 대화방 ID 유효성(공백 및 최대 길이) 검사
def validate_room_id(data: ChatRequest) -> str:
    # 문자열 앞뒤 공백 제거
    room_id = data.room_id.strip()
    # 공백만 있거나 비어있는 경우 422 에러 발생
    if not room_id:
        raise APIError(422, ErrorCode.INVALID_INPUT, "대화방 ID를 입력해 주세요.")
    # 대화방 ID가 64자를 초과할 경우 422 에러 발생
    if len(room_id) > 64:
        raise APIError(422, ErrorCode.INVALID_INPUT, "대화방 ID는 64자 이내로 입력해 주세요.")
    # 유효성 검증을 통과한 정제된 대화방 ID 반환
    return room_id


# 2차 비즈니스 검증: 대화방 이름 유효성(공백 및 최대 길이) 검사
def validate_room_name(data: ChatRequest) -> str:
    # 문자열 앞뒤 공백 제거
    room_name = data.room_name.strip()
    # 공백만 있거나 비어있는 경우 422 에러 발생
    if not room_name:
        raise APIError(422, ErrorCode.INVALID_INPUT, "대화방 이름을 입력해 주세요.")
    # 대화방 이름이 100자를 초과할 경우 422 에러 발생
    if len(room_name) > 100:
        raise APIError(422, ErrorCode.INVALID_INPUT, "대화방 이름은 100자 이내로 입력해 주세요.")
    # 유효성 검증을 통과한 정제된 대화방 이름 반환
    return room_name


# 2차 비즈니스 검증: 사용자 질문 유효성(공백 및 최대 길이) 검사
def validate_question(data: ChatRequest) -> str:
    # 문자열 앞뒤 공백 제거
    question = data.question.strip()
    # 공백만 있거나 비어있는 경우 422 에러 발생
    if not question:
        raise APIError(422, ErrorCode.INVALID_INPUT, "질문을 입력해 주세요.")

    # 환경설정의 최대 길이와 5,000자 중 작은 값을 허용 한도로 설정
    limit = min(config.MAX_QUESTION_LENGTH, 5000)
    # 질문 글자 수가 제한을 초과할 경우 422 에러 발생
    if len(question) > limit:
        raise APIError(422, ErrorCode.INVALID_INPUT, f"질문은 {limit:,}자 이내로 입력해 주세요.")
    # 유효성 검증을 통과한 정제된 질문 반환
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
            "room_id"    : row.room_id,
            "room_name"  : row.room_name,
            "question"   : row.question,
            "answer"     : row.answer,
            "status"     : row.status,
            "created_at" : row.created_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        for row in rows
    ]
