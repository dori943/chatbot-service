from sqlalchemy             import select
from sqlalchemy.exc         import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime               import datetime, timezone

from app.core.config        import AI_CONTEXT_TURNS
from app.core.errors        import APIError, ErrorCode
from app.core.logging       import log_event
from app.schemas.chat       import AIResult
from app.models.chatlog     import ChatLog

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
        log_event("chat_saved", status=result.status, request_id=result.request_id)
        
        return created_at
    except SQLAlchemyError as exc:
        log_event("chat_save_failed", exc=exc, request_id=result.request_id)
        await db.rollback()
        raise APIError(
            503, ErrorCode.DB_UNAVAILABLE,
            "대화 기록을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.", result.request_id,
        ) from None


async def get_list_chat(user_id: str, db: AsyncSession):
    try:
        rows = await db.scalars(
            select(ChatLog)
            .where(ChatLog.user_id == user_id)
            .order_by(ChatLog.created_at.desc(), ChatLog.id.desc())
        )
        chats = list(rows)
        await db.commit()
        log_event("chat_list_loaded", count=len(chats))
        return chats
    except SQLAlchemyError as exc:
        log_event("chat_list_failed", exc=exc)
        await db.rollback()
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "대화 기록을 불러오지 못했습니다.") from None

async def get_history(user_id: str, db: AsyncSession, limit: int = AI_CONTEXT_TURNS) -> list[dict[str, str]]:
    try:
        # 문맥 조회 트랜잭션을 끝내 DB 연결을 반환한 뒤 AI를 기다린다.
        rows = await db.scalars(
            select(ChatLog)
            .where(ChatLog.user_id == user_id, ChatLog.status == "success")
            .order_by(ChatLog.id.desc())
            .limit(limit)
        )
        history = [
            {"question": row.question, "answer": row.answer}
            for row in reversed(rows.all())
        ]
        await db.commit()
        log_event("chat_context_loaded", turns=len(history))
        return history

    except SQLAlchemyError as exc:
        log_event("chat_history_load_failed", exc=exc)
        await db.rollback()
        return []
