"""RUN_BROWSER_TESTS=1일 때 로컬 브라우저로 실제 UI → API → 테스트 DB를 확인한다."""
import os
import socket
import threading
import time
from unittest.mock      import AsyncMock

import pytest
import uvicorn

from app.main           import app
from app.models.chatlog import ChatLog
from app.models.login   import Login
from app.schemas.chat   import AIResult
from app.services       import AI_connect
from app.utils          import security

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="브라우저 테스트는 선택 실행")


def test_login_room_context_and_owner_switch(database, monkeypatch):
    from playwright.sync_api import sync_playwright, expect

    with database() as db:
        db.get(Login, "이건탁").pw = security.hash_password("test-only-123")
        db.commit()

    histories = []

    async def answer(question, history, **kwargs):
        histories.append(history)
        return AIResult(
            status     = "success",
            request_id = kwargs["request_id"],
            model      = "browser-test",
            latency_ms = 1,
            answer     = "브라우저 통합 테스트 답변",
        )

    monkeypatch.setattr(AI_connect, "generate_answer", AsyncMock(side_effect=answer))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", log_config=None, access_log=False))
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
                def send_question(question):
                    page.locator("#question").fill(question)
                    with page.expect_response("**/api/chat") as result:
                        page.locator("#send").click()
                    assert result.value.status == 200
                    assert result.value.request.headers["authorization"].startswith("Bearer ")
                    expect(page.locator("#send")).to_be_enabled()
                    sent = result.value.request.post_data_json
                    assert result.value.json()["room_id"] == sent["room_id"]
                    return sent["room_id"]

                first_room = send_question("브라우저 질문")
                assert histories[-1] == []
                expect(page.locator(".message.assistant .message-text")).to_have_text("브라우저 통합 테스트 답변")
                with database() as db:
                    row = db.query(ChatLog).one()
                    assert (row.user_id, row.room_id) == ("이건탁", first_room)

                assert send_question("같은 방 후속 질문") == first_room
                first_turn = {"question": "브라우저 질문", "answer": "브라우저 통합 테스트 답변"}
                assert histories[-1] == [first_turn]
                page.locator("[data-new]").first.click()
                second_room = send_question("새 방 질문")
                assert second_room != first_room
                assert histories[-1] == []

                page.locator("#history-list button").filter(has_text="브라우저 질문").click()
                assert send_question("기존 방 재개") == first_room
                assert histories[-1] == [
                    first_turn,
                    {"question": "같은 방 후속 질문", "answer": "브라우저 통합 테스트 답변"},
                ]
                page.reload()
                page.locator("#history-list button").filter(has_text="브라우저 질문").click()
                assert send_question("새로고침 후 질문") == first_room
                assert [turn["question"] for turn in histories[-1]] == [
                    "브라우저 질문", "같은 방 후속 질문", "기존 방 재개",
                ]

                page.locator(".delete-chat").click()
                assert send_question("삭제 후 새 질문") not in (first_room, second_room)
                assert histories[-1] == []
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
        assert not thread.is_alive(), "Test server did not stop"
