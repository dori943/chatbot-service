import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_context
from app.main import app
from app.models.chatlog import ChatLog
from app.schemas.chat import AIResult
from app.services import AI_connect, auth


@pytest.fixture
def app_logs(caplog):
    logger = logging.getLogger("app")
    logger.addHandler(caplog.handler)
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)


@pytest.fixture
def client(database):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def records(logs):
    return [record for record in logs.records if record.name.startswith("app.")]


def assert_not_logged(logs, *secrets):
    entries = records(logs)
    formatter = logging.getLogger("app").handlers[0].formatter
    output = "\n".join(formatter.format(record) for record in entries)
    for secret in secrets:
        assert secret not in output
    assert all(record.exc_info is None for record in entries)


def test_chat_request_id_matches_logs_response_and_database(client, database, auth_headers, monkeypatch, app_logs):
    monkeypatch.setattr(AI_connect, "_call_once", AsyncMock(return_value=("private-answer", None, None)))
    response = client.post(
        "/api/chat?private-query=hidden", json={"question": "private-question"},
        headers={**auth_headers, "X-Request-ID": "untrusted-request-id"},
    )
    assert response.status_code == 200
    request_id = response.json()["request_id"]
    assert request_id == response.headers["X-Request-ID"]
    assert len(request_id) == 32
    entries = records(app_logs)
    assert {record.request_id for record in entries} == {request_id}
    for event in ("ai_call_start", "ai_call_success", "chat_saved", "request_completed"):
        assert any(record.getMessage().startswith(event) for record in entries)
    with database() as db:
        assert db.query(ChatLog).one().request_id == request_id
    assert_not_logged(app_logs, "private-question", "private-answer", "private-query", "untrusted-request-id", auth_headers["Authorization"])


@pytest.mark.parametrize("kind,status,code", [
    ("unauthorized", 401, "UNAUTHORIZED"),
    ("validation", 422, "INVALID_INPUT"),
    ("database", 503, "DB_UNAVAILABLE"),
    ("unexpected", 500, "INTERNAL_ERROR"),
])
def test_error_logs_have_request_id_without_sensitive_details(client, monkeypatch, app_logs, kind, status, code):
    payload = {"id": "private-login-id", "pw": "private-password"}
    if kind == "unauthorized":
        response = client.post("/api/chat", json={"question": "private-question"})
    else:
        endpoint = "/auth/login"
        if kind == "validation":
            payload["id"] = ["private-invalid-id"]
        elif kind == "database":
            monkeypatch.setattr(AsyncSession, "get", AsyncMock(side_effect=SQLAlchemyError("private-sql-parameters")))
        else:
            def broken_hash(password):
                raise RuntimeError("private-exception-detail")
            monkeypatch.setattr(auth, "hash_password", broken_hash)
            endpoint = "/auth/register"
        response = client.post(endpoint, json=payload)
    assert response.status_code == status
    request_id = response.json()["request_id"]
    assert request_id == response.headers["X-Request-ID"]
    entries = records(app_logs)
    assert {record.request_id for record in entries} == {request_id}
    failure = next(record for record in entries if record.getMessage().startswith("request_failed"))
    assert code in failure.getMessage()
    assert failure.levelno == (logging.ERROR if status >= 500 else logging.WARNING)
    if kind in ("database", "unexpected"):
        assert any("stack=" in record.getMessage() and "kind=" in record.getMessage() for record in entries)
    assert_not_logged(app_logs, "private-login-id", "private-password", "private-question", "private-invalid-id", "private-sql-parameters", "private-exception-detail")


def test_ai_exception_logs_only_error_kind(client, auth_headers, monkeypatch, app_logs):
    monkeypatch.setattr(AI_connect, "_call_once", AsyncMock(side_effect=RuntimeError("private-provider-body-and-key")))
    monkeypatch.setattr(AI_connect, "AI_MAX_RETRIES", 0)
    monkeypatch.setattr(AI_connect, "AI_FALLBACK_MODEL", "")
    response = client.post("/api/chat", json={"question": "private-question"}, headers=auth_headers)
    assert response.status_code == 502
    entries = records(app_logs)
    assert {record.request_id for record in entries} == {response.json()["request_id"]}
    assert any("kind=RuntimeError" in record.getMessage() for record in entries)
    assert any(record.getMessage().startswith("chat_saved status=error") for record in entries)
    assert_not_logged(app_logs, "private-provider-body-and-key", "private-question", auth_headers["Authorization"])


@pytest.mark.parametrize("retry", [True, False], ids=["retry", "fallback"])
def test_ai_recovery_logs_keep_request_id(client, auth_headers, monkeypatch, app_logs, retry):
    monkeypatch.setattr(AI_connect, "AI_MODEL", "primary")
    monkeypatch.setattr(AI_connect, "AI_FALLBACK_MODEL", "fallback")
    monkeypatch.setattr(AI_connect, "AI_MAX_RETRIES", 1 if retry else 0)
    monkeypatch.setattr(AI_connect, "AI_TOTAL_TIMEOUT_SECONDS", 24)
    monkeypatch.setattr(AI_connect, "AI_TIMEOUT_SECONDS", 10)
    call = AsyncMock(side_effect=[
        (None, "AI_RATE_LIMIT" if retry else "AI_UPSTREAM_ERROR", None),
        ("private-recovered-answer", None, None),
    ])
    monkeypatch.setattr(AI_connect, "_call_once", call)
    response = client.post("/api/chat", json={"question": "private-question"}, headers=auth_headers)
    assert response.status_code == 200
    assert [args.args[0] for args in call.call_args_list] == ["primary", "primary" if retry else "fallback"]
    entries = records(app_logs)
    assert {record.request_id for record in entries} == {response.json()["request_id"]}
    assert any(record.getMessage().startswith("ai_call_fail") for record in entries)
    assert any(record.getMessage().startswith("ai_call_success") for record in entries)
    assert any(record.getMessage().startswith("ai_fallback_start") for record in entries) == (not retry)
    assert_not_logged(app_logs, "private-question", "private-recovered-answer")


def test_ai_fallback_skip_is_logged(client, auth_headers, monkeypatch, app_logs):
    monkeypatch.setattr(AI_connect, "AI_MODEL", "primary")
    monkeypatch.setattr(AI_connect, "AI_FALLBACK_MODEL", "fallback")
    monkeypatch.setattr(AI_connect, "AI_MAX_RETRIES", 0)
    monkeypatch.setattr(AI_connect, "MIN_FALLBACK_BUDGET_SECONDS", float("inf"))
    call = AsyncMock(return_value=(None, "AI_UPSTREAM_ERROR", None))
    monkeypatch.setattr(AI_connect, "_call_once", call)
    response = client.post("/api/chat", json={"question": "private-question"}, headers=auth_headers)
    assert response.status_code == 502
    call.assert_awaited_once()
    skipped = next(record for record in records(app_logs) if record.getMessage().startswith("ai_fallback_skip"))
    assert skipped.request_id == response.json()["request_id"]


def test_ai_config_fallback_logs_omit_exception_details(monkeypatch, app_logs):
    monkeypatch.setattr(AI_connect, "AI_THINKING_LEVEL", "low")
    monkeypatch.setattr(AI_connect.types, "ThinkingConfig", Mock(side_effect=TypeError("private-thinking-option")))
    config = object()
    monkeypatch.setattr(AI_connect.types, "GenerateContentConfig", Mock(side_effect=[TypeError("private-config-detail"), config]))
    assert AI_connect._build_config(AI_connect.PromptPayload(), 1) is config
    entries = records(app_logs)
    assert any(record.getMessage().startswith("ai_config_option_ignored") for record in entries)
    assert any(record.getMessage().startswith("ai_config_fallback") for record in entries)
    assert_not_logged(app_logs, "private-thinking-option", "private-config-detail")


def test_auth_success_logs_omit_credentials_and_token(client, app_logs):
    credentials = {"id": "private-new-user", "pw": "private-new-password"}
    assert client.post("/auth/register", json=credentials).status_code == 200
    response = client.post("/auth/login", json=credentials)
    assert response.status_code == 200
    entries = records(app_logs)
    assert any(record.getMessage() == "auth_register_success" for record in entries)
    login = next(record for record in entries if record.getMessage() == "auth_login_success")
    assert login.request_id == response.headers["X-Request-ID"]
    assert_not_logged(app_logs, *credentials.values(), response.json()["token"])


def test_server_exception_log_omits_exception_message(caplog):
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(caplog.handler)
    try:
        try:
            raise RuntimeError("private-server-exception")
        except RuntimeError as exc:
            logger.error("Exception in ASGI application\n", exc_info=exc)
    finally:
        logger.removeHandler(caplog.handler)
    entry = next(record for record in caplog.records if record.name == "uvicorn.error")
    output = logging.Formatter().format(entry)
    assert "private-server-exception" not in output
    assert "kind=RuntimeError" in output
    assert "test_logging.py:" in output
    assert entry.exc_info is None


@pytest.mark.anyio
async def test_concurrent_requests_keep_separate_log_contexts(database, auth_headers, monkeypatch, app_logs):
    started = 0
    both_started = asyncio.Event()
    observed_ids = {}

    async def answer(question, history, **kwargs):
        nonlocal started
        observed_ids[question] = request_id_context.get()
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=5)
        assert request_id_context.get() == observed_ids[question] == kwargs["request_id"]
        return AIResult(status="success", request_id=kwargs["request_id"], model="test", latency_ms=1, answer="ok")

    monkeypatch.setattr(AI_connect, "generate_answer", answer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(*[
            client.post("/api/chat", json={"question": question}, headers=auth_headers)
            for question in ("first", "second")
        ])
    assert all(response.status_code == 200 for response in responses)
    ids = {response.json()["request_id"] for response in responses}
    assert len(ids) == 2
    assert ids == set(observed_ids.values())
    for request_id in ids:
        entries = [record for record in records(app_logs) if record.request_id == request_id]
        assert sum(record.getMessage().startswith("request_completed") for record in entries) == 1
        assert sum(record.getMessage().startswith("chat_saved") for record in entries) == 1
    assert request_id_context.get() is None
