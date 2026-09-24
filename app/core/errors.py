from fastapi            import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses  import JSONResponse
from sqlalchemy.exc     import SQLAlchemyError
from app.core.logging   import log_event


class APIError(Exception):
    def __init__(
        self,
        status_code : int,
        error_code  : str,
        message     : str,
        request_id  : str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body        = {
            "error_code" : error_code,
            "message"    : message,
            "request_id" : request_id
        }


async def api_error_handler(request: Request, exc: APIError):
    body = {
        **exc.body,
        "request_id": getattr(request.state, "request_id", None) or exc.body["request_id"],
    }
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else {}
    if body["request_id"]:
        headers["X-Request-ID"] = body["request_id"]
    log_event(
        "request_failed",
        status     = exc.status_code,
        error_code = body["error_code"],
        request_id = body["request_id"],
    )
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


async def validation_error_handler(request: Request, exc: RequestValidationError):
    return await api_error_handler(request, APIError(
        422, ErrorCode.INVALID_INPUT, "요청 형식과 입력값을 확인해 주세요.",
    ))


async def database_error_handler(request: Request, exc: SQLAlchemyError):
    log_event("database_failed", exc=exc, request_id=getattr(request.state, "request_id", None))
    return await api_error_handler(request, APIError(
        503, ErrorCode.DB_UNAVAILABLE, "데이터베이스 작업을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ))


async def unexpected_error_handler(request: Request, exc: Exception):
    log_event("unexpected_error", exc=exc, request_id=getattr(request.state, "request_id", None))
    return await api_error_handler(request, APIError(
        500, ErrorCode.INTERNAL, "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ))


class ErrorCode:
    TIMEOUT          = "AI_TIMEOUT"
    RATE_LIMIT       = "AI_RATE_LIMIT"
    UPSTREAM         = "AI_UPSTREAM_ERROR"
    CONNECTION       = "AI_CONNECTION_ERROR"
    BAD_REQUEST      = "AI_BAD_REQUEST"       # 잘못된 모델명, 잘못된 파라미터 등
    BLOCKED          = "AI_BLOCKED"           # 안전 필터에 의해 차단됨
    EMPTY_RESPONSE   = "AI_EMPTY_RESPONSE"
    ANSWER_TOO_LONG  = "AI_ANSWER_TOO_LONG"
    UNKNOWN          = "AI_UNKNOWN_ERROR"
    INVALID_INPUT    = "INVALID_INPUT"
    UNAUTHORIZED     = "UNAUTHORIZED"
    USER_EXISTS      = "USER_ALREADY_EXISTS"
    DB_UNAVAILABLE   = "DB_UNAVAILABLE"
    AUTH_UNAVAILABLE = "AUTH_UNAVAILABLE"
    INTERNAL         = "INTERNAL_ERROR"


USER_MESSAGES: dict[str, str] = {
    ErrorCode.TIMEOUT         : "현재 응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.RATE_LIMIT      : "요청이 많아 잠시 처리가 어려워요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.UPSTREAM        : "AI 서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.CONNECTION      : "AI 서비스에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.BAD_REQUEST     : "요청을 처리할 수 없어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.BLOCKED         : "이 질문에는 답변할 수 없어요. 다른 방식으로 질문해 주세요.",
    ErrorCode.EMPTY_RESPONSE  : "답변을 생성하지 못했어요. 질문을 조금 바꿔서 다시 시도해 주세요.",
    ErrorCode.ANSWER_TOO_LONG : "답변이 5,000자를 초과했습니다. 더 짧은 답변을 요청해 주세요.",
    ErrorCode.UNKNOWN         : "일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
}

AI_ERROR_STATUS = {
    ErrorCode.TIMEOUT    : 504,
    ErrorCode.RATE_LIMIT : 429,
    ErrorCode.BLOCKED    : 422,
}

RETRY_SAME_MODEL = {ErrorCode.RATE_LIMIT, ErrorCode.CONNECTION}

FALLBACK_TRIGGERS = {
    ErrorCode.TIMEOUT,
    ErrorCode.RATE_LIMIT,
    ErrorCode.UPSTREAM,
    ErrorCode.CONNECTION,
    ErrorCode.BAD_REQUEST,
    ErrorCode.EMPTY_RESPONSE,
    ErrorCode.UNKNOWN,
}
