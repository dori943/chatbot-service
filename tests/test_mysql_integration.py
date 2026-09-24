"""API 테스트와 같은 전용 MySQL fixture로 실제 DDL 제약을 확인한다."""
from datetime           import datetime
from uuid               import uuid4

import pytest
from sqlalchemy         import inspect
from sqlalchemy.exc     import DataError, IntegrityError

from app.models.chatlog import ChatLog
from app.models.login   import Login


def test_init_sql_matches_orm(database):
    engine = database.kw["bind"]
    inspector = inspect(engine)
    for model in (Login, ChatLog):
        actual = {c["name"]: c for c in inspector.get_columns(model.__tablename__)}
        assert set(actual) == set(model.__table__.columns.keys())
        for column in model.__table__.columns:
            found = actual[column.name]
            actual_type = str(found["type"].compile(dialect=engine.dialect)).split(" COLLATE ")[0]
            assert actual_type == str(column.type.compile(dialect=engine.dialect))
            assert found["nullable"] == column.nullable
            assert getattr(found["type"], "fsp", None) == getattr(column.type, "fsp", None)
    fk = inspector.get_foreign_keys("chat_logs")[0]
    assert fk["referred_table"] == "login"
    assert fk["constrained_columns"] == ["user_id"]


def test_mysql_5000_character_boundary(database):
    with database() as db:
        row = ChatLog(
            user_id    = "alice",
            question   = "가" * 5000,
            answer     = "🙂" * 5000,
            status     = "success",
            request_id = uuid4().hex,
            created_at = datetime(2026, 1, 1, 0, 0, 0, 123456),
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        assert len(row.question) == len(row.answer) == 5000
        assert row.created_at.microsecond == 123456
        with pytest.raises(DataError):
            row.answer = "가" * 5001
            db.flush()
        db.rollback()


def test_mysql_rejects_chat_for_missing_user(database):
    with database() as db:
        db.add(ChatLog(
            user_id    = "missing-user",
            question   = "question",
            status     = "error",
            request_id = uuid4().hex,
            created_at = datetime.now(),
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        assert db.query(ChatLog).count() == 0
