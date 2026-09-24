from pydantic    import BaseModel
from dataclasses import dataclass


class ChatRequest(BaseModel):
    question: str


@dataclass
class AIResult:
    status            : str                  # "success" | "timeout" | "error"
    request_id        : str
    model             : str                  # AI 처리 결과의 모델명
    latency_ms        : int
    answer            : str | None = None
    error_code        : str | None = None
    user_message      : str | None = None
    prompt_tokens     : int | None = None
    completion_tokens : int | None = None
    fallback_used     : bool = False          # 폴백 처리에 진입했는지
