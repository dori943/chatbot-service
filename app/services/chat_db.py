import logging

from sqlalchemy             import select
from sqlalchemy.exc         import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime               import datetime, timezone

from app.core.config        import AI_CONTEXT_TURNS
from app.schemas.chat       import AIResult
from app.models.chatlog     import ChatLog

logger = logging.getLogger(__name__)

async def save_result(db: AsyncSession, user_id: str, question: str, result: AIResult):
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
        await db.commit()
        
        return created_at
    except SQLAlchemyError:
        await db.rollback()
        raise


async def get_list_chat(user_id: str, db: AsyncSession):
    async with db.begin():
        rows = await db.scalars(
            select(ChatLog)
            .where(ChatLog.user_id == user_id)
            .order_by(ChatLog.created_at.desc(), ChatLog.id.desc())
        )
        return list(rows)

async def get_history(user_id: str, db: AsyncSession, limit: int = AI_CONTEXT_TURNS) -> list[dict[str, str]]:
    try:
        # 문맥 조회 트랜잭션을 끝내 DB 연결을 반환한 뒤 AI를 기다린다.
        async with db.begin():
            rows = await db.scalars(
                select(ChatLog)
                .where(ChatLog.user_id == user_id, ChatLog.status == "success")
                .order_by(ChatLog.id.desc())
                .limit(limit)
            )
            return [
                {"question": row.question, "answer": row.answer}
                for row in reversed(rows.all())
            ]

    except SQLAlchemyError:
        logger.error("chat_history_load_failed")
        return []
