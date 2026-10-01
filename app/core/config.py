from os import getenv


def _num(name: str, default: str, cast):
    """숫자 설정을 읽는다. 비어 있거나 형식이 틀리면 기본값을 쓴다.

    `.env`는 `AI_MODEL=`처럼 값을 비워 기본값을 쓰는 방식을 안내한다.
    숫자 항목에서 같은 방식을 쓰면 임포트 시점에 ValueError로 앱이 죽으므로,
    문자열 설정과 동일하게 빈 값을 기본값으로 되돌린다.
    """
    raw = (getenv(name) or "").strip() or default
    try:
        return cast(raw)
    except ValueError:
        return cast(default)


# 제공사가 허용하는 호출 deadline 하한. 이보다 짧으면 400 INVALID_ARGUMENT로 거부된다.
AI_MIN_DEADLINE_SECONDS  = 10.0

AI_API_KEY               = getenv("AI_API_KEY", "").strip()
AI_MODEL                 = getenv("AI_MODEL", "").strip() or "gemini-3.8-flash"
AI_FALLBACK_MODEL        = getenv("AI_FALLBACK_MODEL", "").strip() or "gemini-3.1-flash-lite"

AI_TIMEOUT_SECONDS       = max(_num("AI_TIMEOUT_SECONDS", "10", float), AI_MIN_DEADLINE_SECONDS)
AI_TOTAL_TIMEOUT_SECONDS = _num("AI_TOTAL_TIMEOUT_SECONDS", "26", float)
AI_MAX_RETRIES           = _num("AI_MAX_RETRIES", "1", int)

AI_CONTEXT_TURNS         = _num("AI_CONTEXT_TURNS", "5", int)
AI_MAX_TOKENS            = _num("AI_MAX_TOKENS", "800", int)
AI_TEMPERATURE           = _num("AI_TEMPERATURE", "0.7", float)

AI_THINKING_LEVEL        = getenv("AI_THINKING_LEVEL", "low").strip()
MAX_QUESTION_LENGTH      = _num("MAX_QUESTION_LENGTH", "5000", int)
MAX_CONTEXT_CHARS        = _num("MAX_CONTEXT_CHARS", "6000", int)

# 남은 예산이 이보다 적으면 폴백 호출을 건너뛴다. 제공사 하한보다 짧게 호출하면
# 어차피 400으로 거부되므로, 실패가 확정된 호출 대신 이전 오류를 유지한다.
MIN_FALLBACK_BUDGET_SECONDS = AI_MIN_DEADLINE_SECONDS

# 같은 모델로 재시도하기 전 대기 시간. 시도 횟수에 비례해 늘어난다.
RETRY_BACKOFF_SECONDS       = 0.5
