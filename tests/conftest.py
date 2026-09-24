import asyncio
import os
from unittest.mock          import AsyncMock

import pytest
from fastapi.testclient     import TestClient
from sqlalchemy             import create_engine, delete
from sqlalchemy.engine      import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm         import sessionmaker
from sqlalchemy.pool        import NullPool

from app                    import db as database_module
from app.main               import app
from app.models.chatlog     import ChatLog
from app.models.login       import Login
from app.schemas.chat       import AIResult
from app.services           import AI_connect
from app.utils              import security


def pytest_configure(config):
    config.addinivalue_line("markers", "live_ai: explicit opt-in Gemini API calls")


@pytest.fixture(autouse=True)
def prevent_accidental_ai_calls(request, monkeypatch):
    if request.node.get_closest_marker("live_ai") and os.getenv("RUN_LIVE_AI") == "1":
        return

    def forbidden_client():
        pytest.fail("Unexpected external AI call; mock the AI or explicitly enable the live test")

    monkeypatch.setattr(AI_connect, "_client", forbidden_client)


@pytest.fixture
def database(monkeypatch):
    configured = os.getenv("MYSQL_TEST_URL")
    if not configured:
        pytest.skip("별도 MySQL 테스트 DB 미지정: MYSQL_TEST_URL 필요")
    url = make_url(configured)
    assert url.get_backend_name() == "mysql", "MySQL 테스트 DB만 허용합니다."
    assert url.database == "chatbot_integration_test", "테스트 전용 DB 이름만 허용합니다."
    engine = create_engine(url.set(drivername="mysql+pymysql"), pool_pre_ping=True)
    async_engine = create_async_engine(url.set(drivername="mysql+aiomysql"), poolclass=NullPool)
    sessions = sessionmaker(engine)

    def clear_database():
        with engine.begin() as connection:
            connection.execute(delete(ChatLog))
            connection.execute(delete(Login))

    clear_database()
    with sessions() as db:
        db.add_all([Login(id=name, pw="unused-test-hash") for name in ("alice", "bob", "이건탁")])
        db.commit()
    monkeypatch.setattr(database_module, "SessionLocal", async_sessionmaker(
        async_engine, autoflush=False, expire_on_commit=False,
    ))
    monkeypatch.setattr(security, "KEY", "local-test-signing-key-at-least-32-bytes")
    try:
        yield sessions
    finally:
        clear_database()
        asyncio.run(async_engine.dispose())
        engine.dispose()


@pytest.fixture
def auth_headers(database):
    return {"Authorization": f"Bearer {security.create_token('alice')}"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def client(database):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def ai_mock(monkeypatch):
    async def answer(question, history, **kwargs):
        return AIResult(
            status     = "success",
            request_id = kwargs["request_id"],
            model      = "test-model",
            latency_ms = 1,
            answer     = "테스트 답변",
        )

    mock = AsyncMock(side_effect=answer)
    monkeypatch.setattr(AI_connect, "generate_answer", mock)
    return mock
