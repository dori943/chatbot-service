"""RUN_BROWSER_TESTS=1일 때 로컬 브라우저로 실제 UI → API → 테스트 DB를 확인한다."""
import os
import socket
import threading
import time
from datetime           import datetime, timedelta, timezone
from unittest.mock      import AsyncMock

import jwt
import pytest
import uvicorn

from app.main           import app
from app.core.errors    import ErrorCode, USER_MESSAGES
from app.models.chatlog import ChatLog
from app.models.login   import Login
from app.schemas.chat   import AIResult
from app.services       import AI_connect
from app.utils          import security

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="브라우저 테스트는 선택 실행")


@pytest.fixture
def browser_page(database):
    from playwright.sync_api import sync_playwright

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
                page.goto(f"http://127.0.0.1:{port}")
                yield page
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "Test server did not stop"


def test_login_room_context_and_owner_switch(database, monkeypatch, browser_page):
    from playwright.sync_api import expect

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
    page = browser_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
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
        assert result.value.json()["room_name"] == sent["room_name"]
        assert sent["room_name"] == page.locator("#conversation-title").inner_text()
        return sent["room_id"]

    first_room = send_question("브라우저 질문")
    assert histories[-1] == []
    expect(page.locator(".message.assistant .message-text")).to_have_text("브라우저 통합 테스트 답변")
    with database() as db:
        row = db.query(ChatLog).one()
        assert (row.user_id, row.room_id) == ("이건탁", first_room)
        assert row.room_name == "브라우저 질문"

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
    with database() as db:
        assert {row.room_name for row in db.query(ChatLog).filter_by(room_id=first_room)} == {"브라우저 질문"}
        assert db.query(ChatLog).filter_by(room_id=second_room).one().room_name == "새 방 질문"

    page.locator(".delete-chat").click()
    assert send_question("삭제 후 새 질문") not in (first_room, second_room)
    assert histories[-1] == []
    page.locator("[data-new]").first.click()
    emoji_title = "가" * 29 + "🙂"
    emoji_room = send_question(emoji_title + " 제목 이후 질문")
    with database() as db:
        assert db.query(ChatLog).filter_by(room_id=emoji_room).one().room_name == emoji_title
    page.locator(".login-button").click()
    expect(page.locator("#header-user")).to_be_hidden()
    expect(page.locator(".message.assistant")).to_have_count(0)
    assert not errors


def set_browser_token(page, token):
    page.evaluate("""token => {
        localStorage.setItem('access_token', token);
        window.dispatchEvent(new StorageEvent('storage', {key: 'access_token'}));
    }""", token)


@pytest.mark.parametrize("kind", ["expired-on-load", "expires-idle", "unauthorized"])
def test_expiry_and_401_clear_token_and_login_ui(browser_page, ai_mock, kind):
    from playwright.sync_api import expect

    page = browser_page
    now = datetime.now(timezone.utc)
    page.clock.install(time=now)
    user_id = "missing-user" if kind == "unauthorized" else "alice"
    token = jwt.encode({"id": user_id, "exp": now + timedelta(seconds=60)}, security.KEY, algorithm="HS256")
    if kind == "expired-on-load":
        token = jwt.encode({"id": user_id, "exp": now - timedelta(seconds=1)}, security.KEY, algorithm="HS256")
        page.evaluate("token => localStorage.setItem('access_token', token)", token)
        page.reload()
    else:
        set_browser_token(page, token)
        expect(page.locator("#header-user")).to_have_text(user_id)
        if kind == "expires-idle":
            page.clock.fast_forward(61_000)
        else:
            page.locator("#question").fill("인증 실패 질문")
            with page.expect_response("**/api/chat") as reply:
                page.locator("#send").click()
            assert reply.value.status == 401
            expect(page.locator("#status")).to_contain_text("로그인")

    expect(page.locator("#header-user")).to_be_hidden()
    expect(page.locator(".login-button")).to_have_text("로그인")
    expect(page.locator(".profile strong")).to_have_text("게스트")
    expect(page.locator(".profile .avatar")).to_have_text("G")
    assert page.evaluate("localStorage.getItem('access_token')") is None
    expect(page.locator("#question")).to_be_enabled()
    ai_mock.assert_not_called()


def test_old_request_401_does_not_remove_new_login(browser_page, ai_mock):
    from playwright.sync_api import expect

    page = browser_page
    now = datetime.now(timezone.utc)
    old_token = jwt.encode({"id": "alice", "exp": now + timedelta(minutes=5)}, security.KEY, algorithm="HS256")
    new_token = jwt.encode({"id": "alice", "exp": now + timedelta(minutes=10)}, security.KEY, algorithm="HS256")
    set_browser_token(page, old_token)

    def unauthorized(route):
        set_browser_token(page, new_token)
        route.fulfill(status=401, json={"message": "이전 요청 인증 만료"})

    page.route("**/api/chat", unauthorized)
    page.locator("#question").fill("이전 토큰 질문")
    page.locator("#send").click()
    expect(page.locator("#status")).to_have_text("이전 요청 인증 만료")
    expect(page.locator("#header-user")).to_have_text("alice")
    assert page.evaluate("localStorage.getItem('access_token')") == new_token
    ai_mock.assert_not_called()


@pytest.mark.parametrize("code,http", [(ErrorCode.CONFIG, 503), (ErrorCode.TOKEN_LIMIT, 502)])
def test_ai_setting_errors_keep_login_and_save_failure(browser_page, database, monkeypatch, code, http):
    from playwright.sync_api import expect

    page = browser_page
    token = security.create_token("alice")
    set_browser_token(page, token)
    call = AsyncMock(return_value=(None, code, None))
    monkeypatch.setattr(AI_connect, "_call_once", call)
    monkeypatch.setattr(AI_connect, "AI_MAX_RETRIES", 2)
    page.locator("#question").fill("AI 설정 오류 질문")
    with page.expect_response("**/api/chat") as reply:
        page.locator("#send").click()
    assert reply.value.status == http
    assert reply.value.json()["error_code"] == code
    expect(page.locator("#status")).to_have_text(USER_MESSAGES[code])
    expect(page.locator("#header-user")).to_have_text("alice")
    assert page.evaluate("localStorage.getItem('access_token')") == token
    call.assert_awaited_once()
    with database() as db:
        row = db.query(ChatLog).one()
        assert (row.status, row.error_code, row.answer) == ("error", code, None)
