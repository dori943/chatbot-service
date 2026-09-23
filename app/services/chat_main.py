from sqlalchemy.orm   import Session

from app.schemas.chat import ChatRequest
from app.services     import chat_db, AI_connect

async def chat(data: ChatRequest, user_id: str, db: Session):
    history = chat_db.get_history(user_id, db)

    result = await AI_connect.generate_answer(
        question = data.question,
        history  = history,
        user_id  = user_id
    )

    chat_db.save_result(
        db       = db,
        user_id  = user_id,
        question = data.question,
        result   = result
    )

    return result

async def get_my_chat(user_id: str, db: Session):
    return chat_db.get_list_chat(user_id, db)