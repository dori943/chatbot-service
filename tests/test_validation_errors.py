import asyncio
from unittest.mock          import AsyncMock

import pytest
from sqlalchemy.exc         import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core               import config
from app.models.chatlog     import ChatLog
from app.schemas.chat       import AIResult
from app.services           import auth


@pytest.mark.parametrize("payload", [
    {}, {"question": ""}, {"question": " \n "}, {"question": "가" * 5001},
    {"question": None}, {"question": 123}, {"question": []},
])
def test_invalid_question_is_rejected_before_ai(client, database, auth_headers, ai_mock, payload):
    response = client.post("/api/chat", json=payload, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_INPUT"
    assert set(response.json()) == {"error_code", "message", "request_id"}
    ai_mock.assert_not_called()
    with database() as db:
        assert db.query(ChatLog).count() == 0


def test_question_boundary_normalization_and_configured_limit(client, database, auth_headers, ai_mock, monkeypatch):
    response = client.post(
        "/api/chat",
        json    = {"question": "  " + "가" * 5000 + "  ", "user_id": "bob"},
        headers = auth_headers,
    )
    assert response.status_code == 200
    assert ai_mock.call_args.kwargs["question"] == "가" * 5000
    with database() as db:
        assert db.query(ChatLog).one().question == "가" * 5000
        assert db.query(ChatLog).one().user_id == "alice"
    monkeypatch.setattr(config, "MAX_QUESTION_LENGTH", 3)
    ai_mock.reset_mock()
    assert client.post("/api/chat", json={"question": "four"}, headers=auth_headers).status_code == 422
    ai_mock.assert_not_called()


@pytest.mark.parametrize("code,status,http", [
    ("AI_TIMEOUT", "timeout", 504), ("AI_RATE_LIMIT", "error", 429),
    ("AI_BLOCKED", "error", 422), ("AI_CONNECTION_ERROR", "error", 502),
    ("AI_UPSTREAM_ERROR", "error", 502), ("AI_BAD_REQUEST", "error", 502),
    ("AI_EMPTY_RESPONSE", "error", 502), ("AI_UNKNOWN_ERROR", "error", 502),
])
def test_ai_failure_is_saved_before_error_response(client, database, auth_headers, ai_mock, code, status, http):
    ai_mock.side_effect = None
    ai_mock.return_value = AIResult(
        status       = status,
        request_id   = "provider-id",
        model        = "test",
        latency_ms   = 1,
        answer       = "discard this failed answer",
        error_code   = code,
        user_message = "private-provider-details",
    )
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == http
    body = response.json()
    assert body["error_code"] == code
    assert body["request_id"]
    assert "private-provider-details" not in response.text
    with database() as db:
        row = db.query(ChatLog).one()
        assert (row.status, row.error_code, row.answer) == (status, code, None)
        assert row.request_id == body["request_id"]


@pytest.mark.parametrize("answer,code", [
    (None, "AI_EMPTY_RESPONSE"), (" \n ", "AI_EMPTY_RESPONSE"),
    (123, "AI_EMPTY_RESPONSE"), ("가" * 5001, "AI_ANSWER_TOO_LONG"),
], ids=["missing", "blank", "wrong-type", "too-long"])
def test_invalid_ai_answer_is_not_saved_as_success(client, database, auth_headers, ai_mock, answer, code):
    ai_mock.side_effect = None
    ai_mock.return_value = AIResult(
        status     = "success",
        request_id = "test",
        model      = "test",
        latency_ms = 1,
        answer     = answer,
    )
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == 502
    assert response.json()["error_code"] == code
    with database() as db:
        row = db.query(ChatLog).one()
        assert row.status == "error"
        assert row.answer is None
        assert row.error_code == code


@pytest.mark.parametrize("kind,code,http", [
    ("exception", "AI_UNKNOWN_ERROR", 502), ("timeout", "AI_TIMEOUT", 504),
    ("invalid-result", "AI_UNKNOWN_ERROR", 502),
])
def test_unexpected_ai_failures_are_recorded(client, database, auth_headers, ai_mock, monkeypatch, kind, code, http):
    if kind == "exception":
        ai_mock.side_effect = RuntimeError("private-provider-error")
    elif kind == "timeout":
        async def slow(**kwargs):
            await asyncio.sleep(10)
        ai_mock.side_effect = slow
        monkeypatch.setattr(config, "AI_TOTAL_TIMEOUT_SECONDS", 0.01)
    else:
        ai_mock.side_effect = None
        ai_mock.return_value = None
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == http
    assert response.json()["error_code"] == code
    assert "private-provider-error" not in response.text
    with database() as db:
        assert db.query(ChatLog).one().error_code == code


def test_save_failure_returns_503_and_rolls_back(client, database, auth_headers, ai_mock, monkeypatch):
    original_commit = AsyncSession.commit

    async def fail_chat_save(db):
        if any(isinstance(row, ChatLog) for row in db.new):
            raise SQLAlchemyError("private-sql")
        await original_commit(db)

    monkeypatch.setattr(AsyncSession, "commit", fail_chat_save)
    response = client.post("/api/chat", json={"question": "hi"}, headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error_code"] == "DB_UNAVAILABLE"
    assert response.json()["request_id"]
    assert "private-sql" not in response.text
    with database() as db:
        assert db.query(ChatLog).count() == 0


def test_history_error_and_response_contract(client, auth_headers, ai_mock, monkeypatch):
    assert client.post("/api/chat", json={"question": "hi"}, headers=auth_headers).status_code == 200
    item = client.get("/api/me/chats", headers=auth_headers).json()[0]
    assert set(item) == {"id", "question", "answer", "status", "created_at"}
    assert item["created_at"].endswith("Z")
    monkeypatch.setattr(AsyncSession, "execute", AsyncMock(side_effect=SQLAlchemyError("private-sql")))
    response = client.get("/api/me/chats", headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error_code"] == "DB_UNAVAILABLE"


@pytest.mark.parametrize("payload", [
    {"id": "", "pw": "valid"}, {"id": "  ", "pw": "valid"},
    {"id": "a" * 51, "pw": "valid"}, {"id": 123, "pw": "valid"},
    {"id": "new", "pw": ""}, {"id": "new", "pw": "   "},
    {"id": "new", "pw": "가" * 25}, {"id": "new", "pw": "a" * 73},
])
def test_auth_validation(client, payload):
    for endpoint in ("/auth/register", "/auth/login"):
        response = client.post(endpoint, json=payload)
        assert response.status_code == 422
        assert response.json()["error_code"] == "INVALID_INPUT"
        assert "input" not in response.json()


def test_auth_boundaries_duplicate_and_wrong_credentials(client):
    credentials = {"id": "a" * 50, "pw": "가" * 24, "admin": True}
    assert client.post("/auth/register", json=credentials).status_code == 200
    assert client.post("/auth/login", json=credentials).status_code == 200
    response = client.post("/auth/register", json=credentials)
    assert response.status_code == 409
    assert response.json()["error_code"] == "USER_ALREADY_EXISTS"
    for invalid in ({**credentials, "pw": "wrong"}, {"id": "not-found", "pw": "wrong"}):
        response = client.post("/auth/login", json=invalid)
        assert response.status_code == 401
        assert response.json()["error_code"] == "UNAUTHORIZED"


def test_auth_database_failure_and_unexpected_error(client, monkeypatch):
    monkeypatch.setattr(AsyncSession, "get", AsyncMock(side_effect=SQLAlchemyError("private-sql")))
    response = client.post("/auth/login", json={"id": "alice", "pw": "test"})
    assert response.status_code == 503
    assert response.json()["error_code"] == "DB_UNAVAILABLE"
    def broken_hash(password):
        raise RuntimeError("private-error")

    monkeypatch.setattr(auth, "hash_password", broken_hash)
    response = client.post("/auth/register", json={"id": "new", "pw": "test"})
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"
    assert "private-error" not in response.text


def test_malformed_json_uses_common_error_format(client, auth_headers):
    response = client.post(
        "/api/chat",
        content = "{",
        headers = {**auth_headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_INPUT"
