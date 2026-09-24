import logging

from fastapi               import APIRouter, Depends
from fastapi.routing       import APIRoute
from sqlalchemy.orm        import Session

from app.core.dependencies import get_token_id
from app.schemas.chat      import ChatRequest
from app.db                import get_db
from app.services          import chat_main

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat")
async def send_chat(data: ChatRequest, user_id: str = Depends(get_token_id), db: Session = Depends(get_db)):
    return await chat_main.chat(data, user_id, db)

@router.get("/me/chats")
async def get_my_chat(user_id: str=Depends(get_token_id), db: Session = Depends(get_db)):
    return await chat_main.get_my_chat(user_id, db)
