from sqlalchemy.orm   import Session

from app.schemas.chat import ChatRequest
from app.services     import chat_db

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