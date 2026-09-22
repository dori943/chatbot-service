"""채팅 결과 저장. AI를 기다리는 동안 DB 세션을 열어 두지 않는다."""
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import APIError
from app.db import SessionLocal
from app.models.chatlog import ChatLog
from app.schemas.chat import ChatLogItem, ChatLogListResponse
from app.services.ai_service import AI_CONTEXT_TURNS, AIResult

logger = logging.getLogger(__name__)


def get_recent_history(
    user_id: str, limit: int = AI_CONTEXT_TURNS
) -> list[dict[str, str]]:
    """문맥 유지용 최근 대화를 '오래된 것부터' 반환한다. (미션 요구사항 3번)

    두 가지가 핵심이다. 하나라도 빠지면 문맥이 깨진다.

    1) status == "success" 필터
       실패한 행은 answer 가 NULL 이라 대화에 섞이면 AI 가 이상하게 답한다.

    2) reversed()
       DB 는 최신순으로 주지만, AI 에는 시간순(오래된 것 → 최신)으로 넣어야 한다.

    정렬을 created_at 이 아니라 id 로 하는 이유:
    같은 마이크로초에 여러 건이 들어오면 순서가 흔들릴 수 있다.
    id 는 autoincrement 라 항상 단조 증가한다.

    조회에 실패하면 빈 리스트를 돌려준다. 문맥이 없어도 답변은 만들 수 있으므로
    여기서 요청 전체를 실패시키지 않는다.
    """
    try:
        with SessionLocal() as db:
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


def save_result(user_id: str, question: str, result: AIResult) -> datetime:
    created_at = datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            row = ChatLog(
                **result.to_log_row(user_id, question),
                # MySQL DATETIME에는 UTC를 시간대 없이 저장한다.
                created_at=created_at.replace(tzinfo=None),
            )
            db.add(row)
            db.commit()
    except SQLAlchemyError:
        # 예외 본문에는 질문/답변 또는 접속 정보가 포함될 수 있어 출력하지 않는다.
        logger.error("chat_save_failed request_id=%s", result.request_id)
        raise APIError(
            503, "DB_UNAVAILABLE", "대화 기록을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            result.request_id,
        ) from None
    logger.info("chat_saved request_id=%s status=%s", result.request_id, result.status)
    return created_at


def list_chats(user_id: str, limit: int, offset: int) -> ChatLogListResponse:
    try:
        with SessionLocal() as db:
            query = db.query(ChatLog).filter(ChatLog.user_id == user_id)
            total = query.count()
            rows = query.order_by(ChatLog.created_at.desc(), ChatLog.id.desc()).offset(offset).limit(limit).all()
            return ChatLogListResponse(
                items=[ChatLogItem.model_validate(row) for row in rows], total=total,
            )
    except SQLAlchemyError:
        logger.error("chat_history_unavailable")
        raise APIError(503, "DB_UNAVAILABLE", "대화 기록을 불러오지 못했습니다.") from None
