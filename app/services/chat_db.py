from sqlalchemy             import select, delete, update, func
from sqlalchemy.exc         import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime               import datetime, timedelta, timezone

from app.core               import config
from app.core.errors        import APIError, ErrorCode
from app.core.logging       import log_event
from app.schemas.chat       import AIResult
from app.models.chatlog     import ChatLog


# AI 호출 전에 질문을 저장하고 DB 연결을 반환한다.
async def save_question(
    db         : AsyncSession,
    user_id    : str,
    room_id    : str,
    room_name  : str,
    question   : str,
    request_id : str,
):
    created_at = datetime.now(timezone.utc)

    try:
        row = ChatLog(
            user_id    = user_id,
            room_id    = room_id,
            room_name  = room_name,
            question   = question,
            status     = "processing",
            request_id = request_id,
            created_at = created_at.replace(tzinfo=None),
        )

        db.add(row)
        await db.commit()
        log_event("chat_started", chat_id=row.id, request_id=request_id)

        return row.id, created_at
    except SQLAlchemyError as exc:
        log_event("chat_save_failed", exc=exc, request_id=request_id)
        await db.rollback()
        raise APIError(
            503, ErrorCode.DB_UNAVAILABLE,
            "대화 기록을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.", request_id,
        ) from None


# 처리 중인 질문에 결과를 저장하며 삭제되거나 종료된 기록은 복원하지 않는다.
async def save_result(db: AsyncSession, chat_id: int, result: AIResult):
    try:
        saved = await db.execute(
            update(ChatLog)
            .where(ChatLog.id == chat_id, ChatLog.status == "processing")
            .values(
                answer=result.answer, status=result.status, error_code=result.error_code,
                latency_ms=result.latency_ms, model=result.model,
            )
        )
        await db.commit()
        if saved.rowcount:
            log_event("chat_saved", status=result.status, request_id=result.request_id)
        return bool(saved.rowcount)
    except SQLAlchemyError as exc:
        log_event("chat_save_failed", exc=exc, request_id=result.request_id)
        await db.rollback()
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "대화 결과를 저장하지 못했습니다.", result.request_id) from None


# 서버 중단 등으로 남은 처리 상태를 AI 제한 시간과 저장 유예 30초 이후 종료한다.
async def expire_processing(user_id: str, db: AsyncSession):
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=config.AI_TOTAL_TIMEOUT_SECONDS + 30)
    expired = await db.execute(
        update(ChatLog)
        .where(ChatLog.user_id == user_id, ChatLog.status == "processing", ChatLog.created_at < cutoff)
        .values(status="error", error_code=ErrorCode.INTERNAL)
    )
    if expired.rowcount:
        await db.commit()
        log_event("chat_processing_expired", count=expired.rowcount)


async def get_list_chat(user_id: str, db: AsyncSession, room_id: str | None = None, before_id: int | None = None):
    try:
        await expire_processing(user_id, db)
        query = (
            select(
                ChatLog.id,
                ChatLog.room_id,
                ChatLog.room_name,
                ChatLog.question,
                ChatLog.answer,
                ChatLog.status,
                ChatLog.error_code,
                ChatLog.created_at,
            )
            .where(ChatLog.user_id == user_id)
        )
        if room_id is not None:
            query = query.where(ChatLog.room_id == room_id).order_by(ChatLog.id.desc()).limit(5)
            if before_id is not None:
                query = query.where(ChatLog.id < before_id)
        else:
            query = query.order_by(ChatLog.created_at.desc(), ChatLog.id.desc())
        rows = await db.execute(query)
        chats = rows.all()
        await db.commit()
        log_event("chat_list_loaded", count=len(chats))
        return chats
    except SQLAlchemyError as exc:
        log_event("chat_list_failed", exc=exc)
        await db.rollback()
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "대화 기록을 불러오지 못했습니다.") from None


async def get_list_rooms(user_id: str, db: AsyncSession):
    try:
        await expire_processing(user_id, db)
        latest = (
            select(func.max(ChatLog.id))
            .where(ChatLog.user_id == user_id)
            .group_by(ChatLog.room_id)
        )
        rows = await db.execute(
            select(ChatLog.room_id, ChatLog.room_name)
            .where(ChatLog.id.in_(latest))
            .order_by(ChatLog.id.desc())
        )
        rooms = rows.all()
        await db.commit()
        log_event("chat_list_loaded", count=len(rooms))
        return rooms
    except SQLAlchemyError as exc:
        log_event("chat_list_failed", exc=exc)
        await db.rollback()
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "대화방 목록을 불러오지 못했습니다.") from None


async def delete_room(user_id: str, room_id: str, db: AsyncSession):
    try:
        result = await db.execute(delete(ChatLog).where(ChatLog.user_id == user_id, ChatLog.room_id == room_id))
        await db.commit()
        log_event("chat_room_deleted", user_id=user_id, room_id=room_id, count=result.rowcount)
        return result.rowcount
    except SQLAlchemyError as exc:
        log_event("chat_room_delete_failed", exc=exc, user_id=user_id, room_id=room_id)
        await db.rollback()
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "대화방을 삭제하지 못했습니다.") from None


async def get_history(
    user_id : str,
    room_id : str,
    db      : AsyncSession,
    limit   : int = config.AI_CONTEXT_TURNS,
) -> list[dict[str, str]]:
    try:
        # 문맥 조회 트랜잭션을 끝내 DB 연결을 반환한 뒤 AI를 기다린다.
        rows = await db.execute(
            select(ChatLog.question, ChatLog.answer)
            .where(
                ChatLog.user_id == user_id,
                ChatLog.room_id == room_id,
                ChatLog.status == "success",
            )
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
