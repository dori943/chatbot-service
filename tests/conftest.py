import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import dependencies
from app.db import Base
from app.models.chatlog import ChatLog  # noqa: F401 - metadata 등록
from app.models.login import Login
from app.utils import security


@pytest.fixture
def database(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add_all([Login(id=name, pw="unused-test-hash") for name in ("alice", "bob", "이건탁")])
        db.commit()
    monkeypatch.setattr(dependencies, "SessionLocal", sessions)
    monkeypatch.setattr(security, "KEY", "local-test-signing-key-at-least-32-bytes")
    yield sessions
    engine.dispose()


@pytest.fixture
def auth_headers(database):
    return {"Authorization": f"Bearer {security.create_token('alice')}"}
