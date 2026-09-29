import asyncio
import time
import uuid

from dataclasses         import dataclass, field
from functools           import lru_cache
from typing              import Any, Iterable
from google              import genai
from google.genai        import errors, types

from app.core.config     import (
    AI_API_KEY,
    AI_MODEL,
    AI_FALLBACK_MODEL,
    AI_TIMEOUT_SECONDS,
    AI_TOTAL_TIMEOUT_SECONDS,
    AI_MAX_RETRIES,
    AI_CONTEXT_TURNS,
    AI_MAX_TOKENS,
    AI_TEMPERATURE,
    AI_THINKING_LEVEL,
    MAX_CONTEXT_CHARS,
    MIN_FALLBACK_BUDGET_SECONDS,
    RETRY_BACKOFF_SECONDS,
)

from app.core.errors     import (
    ErrorCode,
    RETRY_SAME_MODEL,
    FALLBACK_TRIGGERS,
    USER_MESSAGES,
)
from app.core.logging    import log_event
from app.schemas.chat    import AIResult
from app.services.prompt import CONTEXT_TRUNCATED_NOTICE, SYSTEM_PROMPT


@dataclass
class PromptPayload:
    contents           : list[dict[str, Any]] = field(default_factory=list)
    system_instruction : str  = SYSTEM_PROMPT
    turns_used         : int  = 0
    truncated          : bool = False


def build_contents(
    question: str,
    history: Iterable[dict[str, Any]] | None = None,
) -> PromptPayload:
    """성공한 대화를 오래된 순서로 받아 최근 턴과 길이 제한을 적용한다."""
    turns: list[dict[str, Any]] = [
        t for t in (history or [])
        if t.get("question") and t.get("answer")
    ]
    # AI_CONTEXT_TURNS=0 은 문맥을 쓰지 않겠다는 뜻이다.
    # turns[-0:] 는 전체를 남기므로 0을 따로 처리한다.
    turns = turns[-AI_CONTEXT_TURNS:] if AI_CONTEXT_TURNS > 0 else []

    truncated = False
    while turns:
        total = sum(len(t["question"]) + len(t["answer"]) for t in turns)
        if total + len(question) <= MAX_CONTEXT_CHARS:
            break
        turns.pop(0)
        truncated = True

    contents: list[dict[str, Any]] = []
    for turn in turns:
        contents.append({"role": "user" , "parts": [{"text": turn["question"]}]})
        contents.append({"role": "model", "parts": [{"text": turn["answer"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    system_instruction = SYSTEM_PROMPT
    if truncated:
        system_instruction = f"{SYSTEM_PROMPT}\n\n{CONTEXT_TRUNCATED_NOTICE}"

    return PromptPayload(
        contents           = contents,
        system_instruction = system_instruction,
        turns_used         = len(turns),
        truncated          = truncated,
    )


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=AI_API_KEY)


def _classify(exc: Exception) -> str:
    """예외를 우리 에러 코드로 변환한다."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ErrorCode.TIMEOUT

    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        if code in (401, 403):
            return ErrorCode.CONFIG
        if code == 400:
            # 키 오류는 HTTP 400의 구조화된 reason으로도 반환된다.
            details = getattr(exc, "details", {})
            if isinstance(details, dict):
                error = details.get("error", details)
                if isinstance(error, dict):
                    for detail in error.get("details", []) or []:
                        if isinstance(detail, dict) and str(detail.get("reason", "")).startswith("API_KEY_"):
                            return ErrorCode.CONFIG
            if "api key" in str(getattr(exc, "message", "") or "").lower():
                return ErrorCode.CONFIG
        if code == 429:
            return ErrorCode.RATE_LIMIT
        if code in (400, 404):
            return ErrorCode.BAD_REQUEST
        if isinstance(code, int) and code >= 500:
            return ErrorCode.UPSTREAM
        return ErrorCode.UPSTREAM

    # httpx 등 하위 라이브러리 예외는 이름으로 판별 (SDK 버전에 따라 타입이 바뀜)
    name = type(exc).__name__
    if "Timeout" in name:
        return ErrorCode.TIMEOUT
    if "Connect" in name or "Network" in name or "Transport" in name:
        return ErrorCode.CONNECTION
    return ErrorCode.UNKNOWN


def _extract_answer(response: Any) -> tuple[str, str | None]:
    """응답에서 텍스트를 꺼낸다. 실패 시 (빈 문자열, 에러코드)."""
    # 안전 필터에 걸린 경우 prompt_feedback.block_reason 이 채워진다
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        return "", ErrorCode.BLOCKED

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        reason = str(getattr(candidates[0], "finish_reason", "") or "")
        if "MAX_TOKENS" in reason.upper():
            return "", ErrorCode.TOKEN_LIMIT
        if "SAFETY" in reason.upper() or "BLOCK" in reason.upper():
            return "", ErrorCode.BLOCKED

    text = (getattr(response, "text", None) or "").strip()
    if text:
        return text, None
    return "", ErrorCode.EMPTY_RESPONSE


def _build_config(payload: PromptPayload, timeout: float) -> Any:
    """GenerateContentConfig 를 만든다.

    SDK 버전에 따라 지원하지 않는 옵션이 있을 수 있으므로,
    부가 옵션은 실패해도 기본 설정으로 넘어가도록 방어한다.
    """
    base = dict(
        system_instruction = payload.system_instruction,
        temperature        = AI_TEMPERATURE,
        max_output_tokens  = AI_MAX_TOKENS,
        http_options       = types.HttpOptions(timeout=int(timeout * 1000)),  # ms
    )
    extra: dict[str, Any] = {}

    # 함수 호출(AFC)은 쓰지 않는다 — 경고 제거 + 불필요한 왕복 방지
    try:
        extra["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            disable = True
        )
    except Exception:  # noqa: BLE001 - 구버전 SDK
        pass

    # 내부 추론 단계 낮추기 (응답 속도·비용 절감)
    if AI_THINKING_LEVEL:
        try:
            extra["thinking_config"] = types.ThinkingConfig(
                thinking_level = AI_THINKING_LEVEL
            )
        except Exception:  # noqa: BLE001
            log_event("ai_config_option_ignored")

    try:
        return types.GenerateContentConfig(**base, **extra)
    except Exception:  # noqa: BLE001 - 구버전 SDK
        # SDK가 pydantic 모델이라 미지원 옵션은 TypeError가 아니라
        # ValidationError(ValueError)로 올라온다. 예외 종류를 좁히면
        # 이 방어 코드가 동작하지 않아 모든 요청이 같은 오류로 실패한다.
        log_event("ai_config_fallback")
        return types.GenerateContentConfig(**base)


async def _call_once(
    model: str,
    payload: PromptPayload,
    timeout: float,
) -> tuple[str | None, str | None, Any]:
    """모델을 한 번 호출한다. 반환: (answer, error_code, usage_metadata).

    asyncio.wait_for 로 타임아웃을 직접 강제한다.
    SDK 내부 타임아웃 동작에 의존하지 않기 위함이다.
    """
    if not AI_API_KEY or not AI_API_KEY.strip():
        return None, ErrorCode.CONFIG, None
    config = _build_config(payload, timeout)

    response = await asyncio.wait_for(
        _client().aio.models.generate_content(
            model    = model,
            contents = payload.contents,
            config   = config,
        ),
        timeout = timeout,
    )

    text, err = _extract_answer(response)
    if err:
        return None, err, getattr(response, "usage_metadata", None)
    return text, None, getattr(response, "usage_metadata", None)


async def generate_answer(
    question: str,
    history: Iterable[dict[str, Any]] | None = None,
    *,
    user_id: str | None = None,
    request_id: str | None = None,
) -> AIResult:
    """오류 분류에 따라 재시도·폴백을 적용해 AI 응답을 생성한다.

    AI 호출 실패는 AIResult로 반환하고, 작업 취소는 호출자에게 전달한다.
    입력 검증·DB 저장·HTTP 오류 변환은 chat_main에서 처리한다.
    """
    request_id = request_id or uuid.uuid4().hex[:12]
    payload    = build_contents(question, history)

    candidates = [AI_MODEL]
    if AI_FALLBACK_MODEL and AI_FALLBACK_MODEL != AI_MODEL:
        candidates.append(AI_FALLBACK_MODEL)

    log_event(
        "ai_call_start",
        request_id    = request_id,
        model         = AI_MODEL,
        fallback      = AI_FALLBACK_MODEL,
        context_turns = payload.turns_used,
        q_len         = len(question),
    )

    started            = time.perf_counter()
    last_code          = ErrorCode.UNKNOWN
    last_model         = AI_MODEL
    fallback_attempted = False

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def remaining() -> float:
        return AI_TOTAL_TIMEOUT_SECONDS - (time.perf_counter() - started)

    for model_index, model in enumerate(candidates):
        is_fallback = model_index > 0

        # 주 모델은 시도하되, 폴백을 수행할 시간이 부족하면 이전 실패를 유지한다.
        # 제공사 하한보다 짧은 deadline은 400으로 거부되므로 예산을 깎지 않는다.
        if is_fallback and remaining() < MIN_FALLBACK_BUDGET_SECONDS:
            log_event("ai_fallback_skip", model=model, request_id=request_id)
            break

        # 건너뛴 모델이 실패한 모델로 기록되지 않도록 호출이 확정된 뒤에 갱신한다.
        last_model = model
        budget     = AI_TIMEOUT_SECONDS

        if is_fallback:
            fallback_attempted = True
            log_event(
                "ai_fallback_start",
                request_id     = request_id,
                previous_model = candidates[0],
                model          = model,
                error_code     = last_code,
            )

        for attempt in range(AI_MAX_RETRIES + 1):
            try:
                answer, err_code, usage = await _call_once(model, payload, budget)

                if err_code is None:
                    log_event(
                        "ai_call_success",
                        request_id = request_id,
                        model      = model,
                        latency_ms = elapsed_ms(),
                        attempt    = attempt + 1,
                        fallback   = is_fallback,
                        a_len      = len(answer or ""),
                    )
                    return AIResult(
                        status            = "success",
                        request_id        = request_id,
                        model             = model,
                        latency_ms        = elapsed_ms(),
                        answer            = answer,
                        prompt_tokens     = getattr(usage, "prompt_token_count", None),
                        completion_tokens = getattr(usage, "candidates_token_count", None),
                        fallback_used     = is_fallback,
                    )

                last_code = err_code
                log_event(
                    "ai_call_fail",
                    request_id = request_id,
                    model      = model,
                    error_code = err_code,
                    attempt    = attempt + 1,
                )

            except Exception as exc:
                last_code = _classify(exc)
                log_event(
                    "ai_call_fail",
                    request_id = request_id,
                    model      = model,
                    error_code = last_code,
                    attempt    = attempt + 1,
                    exc        = exc,
                )

            # 같은 모델로 재시도할지 판단.
            # 대기 시간까지 포함해 호출 한 번을 온전히 끝낼 여유가 없으면 시작하지 않는다.
            # 그러지 않으면 chat_main의 전체 타임아웃에 잘려 실제 오류 대신 504로 보고된다.
            backoff   = RETRY_BACKOFF_SECONDS * (attempt + 1)
            can_retry = (
                last_code in RETRY_SAME_MODEL
                and attempt < AI_MAX_RETRIES
                and remaining() >= budget + backoff
            )
            if not can_retry:
                break
            await asyncio.sleep(backoff)

        # 폴백으로 넘어갈 만한 실패가 아니면 여기서 종료
        if last_code not in FALLBACK_TRIGGERS:
            break

    status = "timeout" if last_code == ErrorCode.TIMEOUT else "error"
    log_event(
        "ai_call_giveup",
        request_id = request_id,
        model      = last_model,
        error_code = last_code,
        latency_ms = elapsed_ms(),
        fallback   = fallback_attempted,
    )
    return AIResult(
        status        = status,
        request_id    = request_id,
        model         = last_model,
        latency_ms    = elapsed_ms(),
        error_code    = last_code,
        user_message  = USER_MESSAGES.get(last_code, USER_MESSAGES[ErrorCode.UNKNOWN]),
        fallback_used = fallback_attempted,
    )
