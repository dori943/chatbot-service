from fastapi                import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies  import get_token_id
from app.schemas.chat       import ChatRequest
from app.db                 import get_db
from app.services           import chat_main

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def send_chat(
    data    : ChatRequest,
    user_id : str          = Depends(get_token_id),
    db      : AsyncSession = Depends(get_db),
):
    return await chat_main.chat(data, user_id, db)


@router.get("/me/chats")
async def get_my_chat(
    user_id   : str          = Depends(get_token_id),
    db        : AsyncSession = Depends(get_db),
    room_id   : str | None   = None,
    before_id : int | None   = None,
):
    return await chat_main.get_my_chat(user_id, db, room_id, before_id)


@router.get("/me/rooms")
async def get_my_rooms(
    user_id : str          = Depends(get_token_id),
    db      : AsyncSession = Depends(get_db),
):
    return await chat_main.get_my_rooms(user_id, db)


@router.delete("/me/chats")
async def delete_my_chat(
    room_id : str,
    user_id : str          = Depends(get_token_id),
    db      : AsyncSession = Depends(get_db),
):
    return await chat_main.delete_my_chat(user_id, room_id, db)
