"""RUN_BROWSER_TESTS=1일 때 로컬 브라우저로 실제 UI → API → 테스트 DB를 확인한다."""
import os
import socket
import threading
import time
from unittest.mock import AsyncMock

import pytest
import uvicorn

from app.db import get_db
from app.main import app
from app.models.chatlog import ChatLog
from app.models.login import Login
from app.services import ai_service, chat as chat_service
from app.utils import security

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="브라우저 테스트는 선택 실행")


def test_login_send_and_owner_switch(database, monkeypatch):
    from playwright.sync_api import sync_playwright, expect

    monkeypatch.setattr(chat_service, "SessionLocal", database)
    with database() as db:
        db.get(Login, "이건탁").pw = security.hash_password("test-only-123")
        db.commit()

    def test_db():
        with database() as db:
            yield db

    async def answer(question, **kwargs):
        return ai_service.AIResult(
            status="success", request_id=kwargs["request_id"], model="browser-test",
            latency_ms=1, answer="브라우저 통합 테스트 답변",
        )

    monkeypatch.setattr(ai_service, "generate_answer", AsyncMock(side_effect=answer))
    app.dependency_overrides[get_db] = test_db
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=os.getenv("BROWSER_CHANNEL") or None, headless=True)
            try:
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}")
                page.locator("#question").fill("게스트 질문")
                page.locator("#send").click()
                expect(page.locator("#status")).to_contain_text("로그인")
                page.locator(".login-button").click()
                page.locator("#auth-name").fill("이건탁")
                page.locator("#auth-password").fill("test-only-123")
                page.locator(".auth-submit").click()
                expect(page.locator("#header-user")).to_have_text("이건탁")
                page.locator("#question").fill("브라우저 질문")
                with page.expect_response("**/api/chat") as result:
                    page.locator("#send").click()
                assert result.value.status == 200
                assert result.value.request.headers["authorization"].startswith("Bearer ")
                expect(page.locator(".message.assistant .message-text")).to_have_text("브라우저 통합 테스트 답변")
                with database() as db:
                    assert db.query(ChatLog).one().user_id == "이건탁"
                page.locator(".login-button").click()
                expect(page.locator("#header-user")).to_be_hidden()
                expect(page.locator(".message.assistant")).to_have_count(0)
                assert not errors
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        app.dependency_overrides.pop(get_db, None)
