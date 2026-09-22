from sqlalchemy.orm         import Session
from sqlalchemy.exc         import SQLAlchemyError
from datetime               import datetime, timezone

from app.core.config        import AI_CONTEXT_TURNS
from app.services.chat_main import AIResult
from app.models.chatlog     import ChatLog

def save_result(db: Session, user_id: str, question: str, result: AIResult):
    created_at = datetime.now(timezone.utc)

    try:
        row = ChatLog(
            user_id    = user_id,
            question   = question,
            answer     = result.answer,
            status     = result.status,
            error_code = result.error_code,
            latency_ms = result.latency_ms,
            request_id = result.request_id,
            model      = result.model,
            created_at = created_at.replace(tzinfo=None),
        )

        db.add(row)
        db.commit()
        
        return created_at
    except SQLAlchemyError:
        db.rollback()
        raise


async def get_list_chat(user_id: str, db: Session):
    rows = (
        db.query(ChatLog)
        .filter(ChatLog.user_id == user_id)
        .order_by(
            ChatLog.created_at.desc(),
            ChatLog.id.desc(),
        )
        .all()
    )

    return rows

async def get_history(user_id: str, db: Session, limit: int = AI_CONTEXT_TURNS) -> list[dict[str, str]]:
    try:
        rows = (
            db.query(ChatLog)
            .filter(ChatLog.user_id == user_id, ChatLog.status == "success")
            .order_by(ChatLog.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {"question": row.question, "answer": row.answer}
            for row in reversed(rows)
        ]

    except SQLAlchemyError:
        logger.error("chat_history_load_failed")
        return []