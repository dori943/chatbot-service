from dataclasses      import dataclass
from sqlalchemy.orm   import Session

from app.schemas.chat import ChatRequest
from app.services     import chat_db

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

async def chat(data: ChatRequest, user_id: str, db: Session):
    try:
        pass
    except Exception as e:
        pass

async def get_my_chat(user_id: str, db: Session):
    try:
        pass
    except Exception as e:
        pass