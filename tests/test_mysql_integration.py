"""API 테스트와 같은 전용 MySQL fixture로 실제 DDL 제약을 확인한다."""
from datetime           import datetime
from pathlib            import Path
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
            actual_type = str(found["type"].compile(dialect=engine.dialect)).split(" CHARACTER SET ")[0].split(" COLLATE ")[0]
            assert actual_type == str(column.type.compile(dialect=engine.dialect))
            assert found["nullable"] == column.nullable
            assert getattr(found["type"], "fsp", None) == getattr(column.type, "fsp", None)
    fk = inspector.get_foreign_keys("chat_logs")[0]
    assert fk["referred_table"] == "login"
    assert fk["constrained_columns"] == ["user_id"]


def test_mysql_5000_character_boundary(database):
    with database() as db:
        row = ChatLog(
            room_id    = "room-a",
            room_name  = "Test room",
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
            room_id    = "room-a",
            room_name  = "Test room",
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


def test_verification_sql_separates_processing_from_failures(database):
    with database() as db:
        for status in ("success", "processing", "error", "timeout"):
            db.add(ChatLog(user_id="alice", room_id="room-a", room_name="Room", question="question",
                           status=status, error_code="AI_TIMEOUT" if status == "timeout" else None,
                           request_id=uuid4().hex, created_at=datetime.now()))
        db.commit()

    script = Path("scripts/check_logs.sql").read_text(encoding="utf-8")
    with database.kw["bind"].connect() as connection:
        results = [connection.exec_driver_sql(statement).mappings().all()
                   for statement in script.split(";") if statement.strip()]
    overall = next(rows[0] for rows in results if rows and "users" in rows[0])
    assert (overall["chats"], overall["successes"], overall["processing"], overall["failures"]) == (4, 1, 1, 2)
    users = next(rows for rows in results if rows and "avg_success_ms" in rows[0])
    alice = next(row for row in users if row["user_id"] == "alice")
    bob = next(row for row in users if row["user_id"] == "bob")
    assert (alice["processing"], alice["failures"]) == (1, 2)
    assert (bob["chats"], bob["processing"], bob["failures"]) == (0, 0, 0)
    failures = next(rows for rows in results if rows and "status" in rows[0] and "answer" not in rows[0])
    assert {row["status"] for row in failures} == {"error", "timeout"}
