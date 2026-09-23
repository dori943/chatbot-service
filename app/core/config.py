from os import getenv

AI_API_KEY          = getenv("AI_API_KEY", "")        .strip()
AI_MODEL            = getenv("AI_MODEL", "")          .strip() or "gemini-3.8-flash"
AI_FALLBACK_MODEL   = getenv("AI_FALLBACK_MODEL", "") .strip() or "gemini-3.1-flash-lite"

AI_TIMEOUT          = float(getenv("AI_TIMEOUT"      , "10"))
AI_TOTAL_TIMEOUT    = float(getenv("AI_TOTAL_TIMEOUT", "24"))
AI_MAX_RETRIES      = int(  getenv("AI_MAX_RETRIES"  , "1"))

AI_CONTEXT_TURNS    = int(  getenv("AI_CONTEXT_TURNS", "5"))
AI_MAX_TOKENS       = int(  getenv("AI_MAX_TOKENS"   , "800"))
AI_TEMPERATURE      = float(getenv("AI_TEMPERATURE"  , "0.7"))

AI_THINKING_LEVEL   = getenv("AI_THINKING_LEVEL"  , "low").strip()
MAX_QUESTION_LENGTH = int(getenv("MAX_QUESTION_LENGTH", "5000"))
MAX_CONTEXT_CHARS   = int(getenv("MAX_CONTEXT_CHARS"  , "6000"))

MIN_FALLBACK_BUDGET_SECONDS = 0.5