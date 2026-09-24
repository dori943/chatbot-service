from pydantic    import BaseModel
from dataclasses import dataclass
from datetime    import datetime

class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer     : str
    request_id : str
    created_at : datetime


@dataclass
class AIResult:
    status            : str                  # "success" | "timeout" | "error"
    request_id        : str
    model             : str                  # 실제로 응답을 만든(또는 마지막으로 시도한) 모델
    latency_ms        : int
    answer            : str | None = None
    error_code        : str | None = None
    user_message      : str | None = None    
    prompt_tokens     : int | None = None
    completion_tokens : int | None = None
    fallback_used     : bool = False         # 폴백 모델이 응답했는지
