from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat       import ChatRequest, ChatResponse
from app.services           import chat_db, AI_connect

async def chat(data: ChatRequest, user_id: str, db: AsyncSession):
    history = await chat_db.get_history(user_id, db)

    result = await AI_connect.generate_answer(
        question = data.question,
        history  = history,
        user_id  = user_id
    )

    created_at = await chat_db.save_result(
        db       = db,
        user_id  = user_id,
        question = data.question,
        result   = result
    )

    if result.status != "success":
        return result

    return ChatResponse(
        answer     = result.answer,
        request_id = result.request_id,
        created_at = created_at,
    )

async def get_my_chat(user_id: str, db: AsyncSession):
    return await chat_db.get_list_chat(user_id, db)
