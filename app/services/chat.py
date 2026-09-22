"""채팅 결과 저장. AI를 기다리는 동안 DB 세션을 열어 두지 않는다."""
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import APIError
from app.db import SessionLocal
from app.models.chatlog import ChatLog
from app.services.ai_service import AIResult

logger = logging.getLogger(__name__)


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
