"""MYSQL_TEST_URL로 지정한 별도 테스트 DB에서만 실행한다. 기존 개발 DB 사용 금지."""
import os
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError
from sqlalchemy.orm import sessionmaker

from app.core import dependencies
from app.db import get_db
from app.main import app
from app.models.chatlog import ChatLog
from app.models.login import Login
from app.services import ai_service, chat as chat_service
from app.utils import security

pytestmark = pytest.mark.skipif(not os.getenv("MYSQL_TEST_URL"), reason="별도 MySQL 테스트 DB 미지정")


@pytest.fixture
def mysql_database(monkeypatch):
    url = make_url(os.environ["MYSQL_TEST_URL"])
    assert url.database == "chatbot_integration_test", "테스트 전용 DB 이름만 허용합니다."
    engine = create_engine(url, pool_pre_ping=True)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(dependencies, "SessionLocal", sessions)
    monkeypatch.setattr(chat_service, "SessionLocal", sessions)
    monkeypatch.setattr(security, "KEY", "local-test-signing-key-at-least-32-bytes")

    def test_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    yield engine, sessions
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_init_sql_matches_orm(mysql_database):
    engine, _ = mysql_database
    inspector = inspect(engine)
    for model in (Login, ChatLog):
        actual = {c["name"]: c for c in inspector.get_columns(model.__tablename__)}
        assert set(actual) == set(model.__table__.columns.keys())
        for column in model.__table__.columns:
            found = actual[column.name]
            # 서버 기본 collation은 reflection에만 명시되므로 타입/길이와 별도로 비교한다.
            actual_type = str(found["type"].compile(dialect=engine.dialect)).split(" COLLATE ")[0]
            assert actual_type == str(column.type.compile(dialect=engine.dialect))
            assert found["nullable"] == column.nullable
            assert getattr(found["type"], "fsp", None) == getattr(column.type, "fsp", None)
    fk = inspector.get_foreign_keys("chat_logs")[0]
    assert fk["referred_table"] == "login"
    assert fk["constrained_columns"] == ["user_id"]


def test_mysql_5000_character_boundary(mysql_database):
    _, sessions = mysql_database
    user_id = "boundary-" + uuid4().hex
    with sessions() as db:
        db.add(Login(id=user_id, pw="test-only"))
        db.flush()
        row = ChatLog(
            user_id=user_id, question="가" * 5000, answer="😀" * 5000, status="success",
            request_id=uuid4().hex, created_at=datetime(2026, 1, 1, 0, 0, 0, 123456),
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


def test_register_login_chat_and_history_on_mysql(mysql_database, monkeypatch):
    _, sessions = mysql_database
    user_id = "flow-" + uuid4().hex

    async def answer(question, **kwargs):
        return ai_service.AIResult(
            status="success", request_id=kwargs["request_id"], model="test-model",
            latency_ms=10, answer="MySQL 통합 테스트 답변",
        )

    monkeypatch.setattr(ai_service, "generate_answer", AsyncMock(side_effect=answer))
    with TestClient(app) as client:
        response = client.post("/auth/register", json={"id": user_id, "pw": "test-only-123"})
        assert response.status_code == 200
        login = client.post("/auth/login", json={"id": user_id, "pw": "test-only-123"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        response = client.post("/api/chat", json={"question": "안녕"}, headers=headers)
        assert response.status_code == 200
        history = client.get("/api/me/chats", headers=headers).json()
        assert history["total"] == 1
        assert history["items"][0]["answer"] == response.json()["answer"]
        with sessions() as db:
            assert db.query(ChatLog).filter_by(user_id=user_id).one().request_id == response.json()["request_id"]


@pytest.mark.skipif(os.getenv("RUN_LIVE_AI") != "1", reason="실제 유료 AI 호출은 명시적으로 실행")
def test_live_ai_on_mysql(mysql_database, monkeypatch):
    assert ai_service.AI_API_KEY, "AI_API_KEY가 필요합니다."
    user_id = "live-" + uuid4().hex
    _, sessions = mysql_database
    with sessions() as db:
        db.add(Login(id=user_id, pw="test-only"))
        db.commit()
    headers = {"Authorization": f"Bearer {security.create_token(user_id)}"}
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"question": "안녕이라고 한 단어로 답해줘."}, headers=headers)
        assert response.status_code == 200, f"Live AI status={response.status_code}, code={response.json().get('error_code')}"
        assert response.json()["answer"].strip()
        history = client.get("/api/me/chats", headers=headers).json()
        assert history["items"][0]["answer"] == response.json()["answer"]
