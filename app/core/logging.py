import logging
import time
import traceback

from contextvars     import ContextVar
from pathlib         import Path
from uuid            import uuid4
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_context = ContextVar("request_id", default=None)
logger = logging.getLogger(__name__)

# 로그 레벨과 문구는 이곳에서만 관리한다. 호출부는 이벤트와 필요한 값만 전달한다.
LOG_EVENTS = {
    "request_completed"          : (logging.INFO,    "method=%(method)s route=%(route)s status=%(status)d latency_ms=%(latency_ms)d"),
    "request_failed"             : (logging.WARNING, "status=%(status)d error_code=%(error_code)s"),
    "database_failed"            : (logging.ERROR,   ""),
    "unexpected_error"           : (logging.ERROR,   ""),
    "auth_user_lookup_failed"    : (logging.ERROR,   ""),
    "auth_register_failed"       : (logging.ERROR,   ""),
    "auth_register_success"      : (logging.INFO,    ""),
    "auth_login_lookup_failed"   : (logging.ERROR,   ""),
    "auth_password_verify_failed": (logging.ERROR,   ""),
    "auth_login_success"         : (logging.INFO,    ""),
    "chat_saved"                 : (logging.INFO,    "status=%(status)s"),
    "chat_save_failed"           : (logging.ERROR,   ""),
    "chat_list_loaded"           : (logging.INFO,    "count=%(count)d"),
    "chat_list_failed"           : (logging.ERROR,   ""),
    "chat_context_loaded"        : (logging.INFO,    "turns=%(turns)d"),
    "chat_history_load_failed"   : (logging.ERROR,   ""),
    "chat_ai_failed"             : (logging.ERROR,   ""),
    "ai_config_option_ignored"   : (logging.WARNING, "option=thinking_level"),
    "ai_config_fallback"         : (logging.WARNING, "reason=unsupported_option"),
    "ai_call_start"              : (logging.INFO,    "model=%(model)s fallback=%(fallback)s context_turns=%(context_turns)d q_len=%(q_len)d"),
    "ai_fallback_skip"           : (logging.WARNING, "model=%(model)s reason=no_time_budget"),
    "ai_fallback_start"          : (logging.WARNING, "from=%(previous_model)s to=%(model)s cause=%(error_code)s"),
    "ai_call_success"            : (logging.INFO,    "model=%(model)s latency_ms=%(latency_ms)d attempt=%(attempt)d fallback=%(fallback)s a_len=%(a_len)d"),
    "ai_call_fail"               : (logging.WARNING, "model=%(model)s error_code=%(error_code)s attempt=%(attempt)d"),
    "ai_call_giveup"             : (logging.ERROR,   "model=%(model)s error_code=%(error_code)s latency_ms=%(latency_ms)d fallback=%(fallback)s"),
}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_context.get() or "-"
        return True


def exception_location(exc: Exception) -> str:
    return " > ".join(
        f"{Path(frame.f_code.co_filename).name}:{line}:{frame.f_code.co_name}"
        for frame, line in traceback.walk_tb(exc.__traceback__)
    ) or "-"


class ServerExceptionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn이 처리된 500 예외를 원문 traceback으로 다시 출력하지 않게 한다.
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            record.msg = "server_exception kind=%s stack=%s"
            record.args = (type(exc).__name__, exception_location(exc))
            record.exc_info = None
            record.exc_text = None
        return True


def configure_logging():
    app_logger = logging.getLogger("app")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(RequestIdFilter())
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(filename)s:%(lineno)d request_id=%(request_id)s %(message)s"
        ))
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False
    server_logger = logging.getLogger("uvicorn.error")
    if not any(isinstance(item, ServerExceptionFilter) for item in server_logger.filters):
        server_logger.addFilter(ServerExceptionFilter())


def log_event(event: str, *, request_id: str | None = None, exc: Exception | None = None, **values):
    level, template = LOG_EVENTS[event]
    if event == "request_failed" and values["status"] >= 500:
        level = logging.ERROR

    message = event
    if template:
        message += " " + template % values
    if exc is not None:
        # 예외 원문·SQL 파라미터·지역 변수 대신 오류 종류와 발생 위치만 기록한다.
        message += f" kind={type(exc).__name__} stack={exception_location(exc)}"

    logger.log(
        level, "%s", message,
        extra={"request_id": request_id or request_id_context.get() or "-"},
        stacklevel=2,
    )


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_response(message: Message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [(key, value) for key, value in message.get("headers", [])
                           if key.lower() != b"x-request-id"]
                message["headers"] = headers + [(b"x-request-id", request_id.encode("ascii"))]
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            # 경로 원문과 쿼리 문자열에는 입력값이 들어갈 수 있어 라우트 패턴만 기록한다.
            route = getattr(scope.get("route"), "path", "<unmatched>")
            log_event(
                "request_completed",
                method     = scope["method"],
                route      = route,
                status     = status_code,
                latency_ms = int((time.perf_counter() - started) * 1000),
            )
            request_id_context.reset(token)
