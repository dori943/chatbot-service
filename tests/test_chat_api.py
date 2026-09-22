from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.models.chatlog import ChatLog
from app.services import ai_service, chat as chat_service
from app.utils import security


@pytest.fixture
def client(database, monkeypatch):
    monkeypatch.setattr(chat_service, "SessionLocal", database)
    monkeypatch.setattr(ai_service, "MAX_QUESTION_LENGTH", 5000)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def ai_mock(monkeypatch):
    async def answer(question, **kwargs):
        return ai_service.AIResult(
            status="success", request_id=kwargs["request_id"], model="test-model",
            latency_ms=12, answer="테스트 답변",
        )
    mock = AsyncMock(side_effect=answer)
    monkeypatch.setattr(ai_service, "generate_answer", mock)
    return mock


def test_question_response_and_persistence(client, database, auth_headers, ai_mock):
    response = client.post("/api/chat", json={"question": "  안녕  "}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "테스트 답변"
    assert body["created_at"].endswith("Z")
    with database() as db:
        row = db.query(ChatLog).one()
        assert (row.user_id, row.question, row.answer, row.status) == ("alice", "안녕", body["answer"], "success")
        assert row.request_id == body["request_id"]
        assert row.latency_ms == 12
        assert row.created_at is not None
    assert ai_mock.call_args.kwargs["user_id"] == "alice"
    assert "history" not in ai_mock.call_args.kwargs


@pytest.mark.parametrize("payload", [
    {}, {"question": ""}, {"question": "  "}, {"question": "가" * 5001},
    {"question": None}, {"question": 123}, {"question": "hi", "user_id": "bob"},
])
def test_invalid_input_never_calls_ai(client, database, auth_headers, ai_mock, payload):
    response = client.post("/api/chat", json=payload, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_INPUT"
    ai_mock.assert_not_called()
    with database() as db:
        assert db.query(ChatLog).count() == 0


def test_question_boundary(client, auth_headers, ai_mock):
    response = client.post("/api/chat", json={"question": " " + "가" * 5000 + " "}, headers=auth_headers)
    assert response.status_code == 200


def test_auth_required_before_ai(client, ai_mock):
    assert client.post("/api/chat", json={"question": "hi"}).status_code == 401
    ai_mock.assert_not_called()


@pytest.mark.parametrize("code,status,http", [
    ("AI_TIMEOUT", "timeout", 504), ("AI_RATE_LIMIT", "error", 429),
    ("AI_BLOCKED", "error", 422), ("AI_CONNECTION_ERROR", "error", 502),
])
def test_ai_failures_are_saved(client, database, auth_headers, ai_mock, code, status, http):
    ai_mock.side_effect = None
    ai_mock.return_value = ai_service.AIResult(
        status=status, request_id="failure-test", model="test", latency_ms=20,
        error_code=code, user_message="다시 시도해 주세요.",
    )
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == http
    assert response.json()["error_code"] == code
    with database() as db:
        row = db.query(ChatLog).one()
        assert (row.status, row.error_code, row.answer) == (status, code, None)


@pytest.mark.parametrize("answer,code", [("가" * 5001, "AI_ANSWER_TOO_LONG"), ("  ", "AI_EMPTY_RESPONSE")])
def test_invalid_answer_is_not_saved_as_success(client, database, auth_headers, ai_mock, answer, code):
    ai_mock.side_effect = None
    ai_mock.return_value = ai_service.AIResult(
        status="success", request_id="invalid-answer", model="test", latency_ms=0, answer=answer,
    )
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == 502
    assert response.json()["error_code"] == code
    with database() as db:
        row = db.query(ChatLog).one()
        assert row.status == "error"
        assert row.answer is None


def test_unexpected_exception_is_recorded(client, database, auth_headers, ai_mock):
    ai_mock.side_effect = RuntimeError("secret-provider-detail")
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == 502
    assert "secret-provider-detail" not in response.text
    with database() as db:
        assert db.query(ChatLog).one().error_code == "AI_UNKNOWN_ERROR"


def test_total_timeout_is_recorded(client, database, auth_headers, ai_mock, monkeypatch):
    import asyncio

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    ai_mock.side_effect = slow
    monkeypatch.setattr(ai_service, "AI_TOTAL_TIMEOUT_SECONDS", 0.01)
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == 504
    with database() as db:
        assert db.query(ChatLog).one().status == "timeout"


def test_database_failure_is_not_reported_as_success(client, auth_headers, ai_mock, monkeypatch):
    def unavailable():
        raise OperationalError("private sql", {}, Exception("private connection"))

    monkeypatch.setattr(chat_service, "SessionLocal", unavailable)
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error_code"] == "DB_UNAVAILABLE"
    assert "private" not in response.text


def test_home_and_openapi_start(client):
    assert client.get("/").status_code == 200
    assert "/api/chat" in client.get("/openapi.json").json()["paths"]


def test_history_ownership_and_pagination(client, auth_headers, ai_mock):
    for question in ("first", "second"):
        assert client.post("/api/chat", json={"question": question}, headers=auth_headers).status_code == 200
    bob_headers = {"Authorization": f"Bearer {security.create_token('bob')}"}
    assert client.post("/api/chat", json={"question": "bob-private"}, headers=bob_headers).status_code == 200
    response = client.get("/api/me/chats?limit=1&offset=0&user_id=bob", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["question"] == "second"
    assert response.json()["items"][0]["created_at"].endswith("Z")
    assert "bob-private" not in response.text
    page2 = client.get("/api/me/chats?limit=1&offset=1", headers=auth_headers).json()
    assert page2["items"][0]["question"] == "first"
    assert client.get("/api/me/chats?offset=2", headers=auth_headers).json()["items"] == []
    assert client.get("/api/me/chats", headers=bob_headers).json()["total"] == 1


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])
def test_history_validates_pagination(client, auth_headers, query):
    response = client.get(f"/api/me/chats?{query}", headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_history_requires_authentication(client):
    assert client.get("/api/me/chats").status_code == 401


def test_failed_answer_appears_in_history(client, auth_headers, ai_mock):
    ai_mock.side_effect = RuntimeError("provider-down")
    assert client.post("/api/chat", json={"question": "failed"}, headers=auth_headers).status_code == 502
    row = client.get("/api/me/chats", headers=auth_headers).json()["items"][0]
    assert row["question"] == "failed"
    assert row["status"] == "error"
    assert row["answer"] is None
