import asyncio
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app import db as database_module
from app.db import get_db
from app.main import app
from app.models.chatlog import ChatLog
from app.schemas.chat import AIResult
from app.services import AI_connect, auth, chat_db


@pytest.mark.anyio
async def test_chat_releases_db_while_waiting_and_returns_saved_timestamp(database, auth_headers, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    sessions = []
    histories = []

    async def test_db():
        async with database_module.SessionLocal() as db:
            sessions.append(db)
            yield db

    async def answer(question, history, **kwargs):
        histories.append(history)
        started.set()
        await release.wait()
        return AIResult(
            status="success", request_id="async-chat-test", model="test-model",
            latency_ms=1, answer="테스트 답변",
        )

    monkeypatch.setattr(AI_connect, "generate_answer", answer)
    app.dependency_overrides[get_db] = test_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            pending = asyncio.create_task(client.post(
                "/api/chat", json={"question": "안녕"}, headers=auth_headers,
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                assert not sessions[0].in_transaction()
                response = await asyncio.wait_for(client.get("/api/me/chats", headers=auth_headers), timeout=5)
                assert response.status_code == 200
                assert response.json() == []
            finally:
                release.set()
                response = await pending

            assert response.status_code == 200
            body = response.json()
            assert set(body) == {"answer", "request_id", "created_at"}
            assert body["created_at"].endswith("Z")
            with database() as db:
                saved = db.query(ChatLog).one()
                assert saved.answer == body["answer"]
                assert saved.request_id == body["request_id"]
                assert saved.created_at.replace(tzinfo=timezone.utc) == datetime.fromisoformat(body["created_at"])

            response = await client.post("/api/chat", json={"question": "이어서"}, headers=auth_headers)
            assert response.status_code == 200
            assert histories == [[], [{"question": "안녕", "answer": "테스트 답변"}]]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.anyio
async def test_password_hashing_allows_other_requests_to_progress(database, auth_headers, monkeypatch):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()

    def slow_hash(password):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=10), "Request handling blocked while hashing"
        return "test-hash"

    monkeypatch.setattr(auth, "hash_password", slow_hash)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        pending = asyncio.create_task(client.post("/auth/register", json={"id": "new-user", "pw": "test-password"}))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            response = await asyncio.wait_for(client.get("/api/me/chats", headers=auth_headers), timeout=5)
            assert response.status_code == 200
            assert not pending.done()
        finally:
            release.set()
            response = await pending
        assert response.status_code == 200


@pytest.mark.anyio
async def test_register_login_and_unpaginated_history(database, monkeypatch):
    async def answer(question, history, **kwargs):
        return AIResult(status="success", request_id=question, model="test", latency_ms=1, answer=question)

    monkeypatch.setattr(AI_connect, "generate_answer", answer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        credentials = {"id": "한글사용자", "pw": "test-only-password"}
        assert (await client.post("/auth/register", json=credentials)).status_code == 200
        failed = await client.post("/auth/login", json={**credentials, "pw": "wrong"})
        assert failed.json()["message"] == "login failed"
        response = await client.post("/auth/login", json=credentials)
        assert response.json()["message"] == "login success"
        headers = {"Authorization": f"Bearer {response.json()['token']}"}
        for question in ("first", "second"):
            response = await client.post("/api/chat", json={"question": question}, headers=headers)
            assert response.status_code == 200
        response = await client.get("/api/me/chats", headers=headers)
        assert [row["question"] for row in response.json()] == ["second", "first"]


@pytest.mark.anyio
async def test_history_failure_rolls_back_before_reusing_session(database, monkeypatch):
    async with database_module.SessionLocal() as db:
        original = db.scalars

        async def fail_query(*args, **kwargs):
            from sqlalchemy import text
            await db.execute(text("SELECT * FROM missing_test_table"))

        monkeypatch.setattr(db, "scalars", fail_query)
        assert await chat_db.get_history("alice", db) == []
        assert not db.in_transaction()
        monkeypatch.setattr(db, "scalars", original)
        result = AIResult(status="success", request_id="after-rollback", model="test", latency_ms=1, answer="ok")
        await chat_db.save_result(db, "alice", "question", result)
        assert len(await chat_db.get_list_chat("alice", db)) == 1


def test_timeout_environment_names():
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "from app.core.config import AI_TIMEOUT_SECONDS, AI_TOTAL_TIMEOUT_SECONDS; "
         "assert AI_TIMEOUT_SECONDS == 2.5; assert AI_TOTAL_TIMEOUT_SECONDS == 7.5"],
        env={**os.environ, "AI_TIMEOUT_SECONDS": "2.5", "AI_TOTAL_TIMEOUT_SECONDS": "7.5"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
