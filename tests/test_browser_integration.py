"""RUN_BROWSER_TESTS=1일 때 로컬 브라우저로 실제 UI → API → 테스트 DB를 확인한다."""
import asyncio
import os
import socket
import threading
import time
from datetime           import datetime, timedelta, timezone
from unittest.mock      import AsyncMock
from uuid               import uuid4

import jwt
import pytest
import uvicorn

from app.main           import app
from app.core.errors    import ErrorCode
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


def test_mobile_drawer_closes_when_switching_to_desktop(browser_page):
    from playwright.sync_api import expect

    page = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator(".menu-button").click()
    expect(page.locator(".scrim")).to_be_visible()
    expect(page.locator(".menu-button")).to_have_attribute("aria-expanded", "true")

    page.set_viewport_size({"width": 760, "height": 844})
    expect(page.locator(".scrim")).to_be_visible()
    page.set_viewport_size({"width": 761, "height": 844})
    expect(page.locator(".scrim")).to_be_hidden()
    expect(page.locator(".menu-button")).to_have_attribute("aria-expanded", "false")
    expect(page.locator(".sidebar.is-open")).to_have_count(0)
    page.locator(".login-button").click()
    expect(page.locator(".auth-dialog")).to_be_visible()
    page.locator("[data-close]").click()

    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(".scrim")).to_be_hidden()
    page.locator(".menu-button").click()
    expect(page.locator(".scrim")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".scrim")).to_be_hidden()


def test_auth_error_toast_survives_previous_chat_toast_timer(browser_page, ai_mock):
    from playwright.sync_api import expect

    page = browser_page
    page.clock.install()
    page.reload()
    set_browser_token(page, security.create_token("alice"))
    page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {
        configurable: true, value: { writeText: async () => {} }
    })""")
    page.locator(".question").fill("질문")
    page.locator(".send-button").click()
    page.locator(".message.assistant .copy-button").click()
    expect(page.locator(".toast")).to_have_text("답변을 복사했습니다.")

    page.clock.fast_forward(2000)
    page.evaluate("""() => {
        Storage.prototype.removeItem = () => { throw new Error('blocked'); };
    }""")
    page.locator(".login-button").click()
    expect(page.locator(".toast")).to_contain_text("로그인 정보를 삭제하지 못했습니다")
    page.clock.fast_forward(2000)
    expect(page.locator(".toast")).to_be_visible()
    expect(page.locator(".header-user")).to_be_hidden()


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


def seed_rooms(database, rooms, user_id="alice"):
    with database() as db:
        for room in rooms:
            db.add(ChatLog(
                user_id=user_id, room_id=room["id"], room_name=room["title"],
                question=room.get("question", "이전 질문"), answer=room.get("answer", "이전 답변"),
                status="success", request_id=uuid4().hex, created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
        db.commit()


@pytest.mark.parametrize("height", [720, 6000])
def test_history_loads_five_turns_at_a_time_and_preserves_scroll(browser_page, database, height):
    from playwright.sync_api import expect

    page = browser_page
    page.set_viewport_size({"width": 1280, "height": height})
    seed_rooms(database, [{"id": "paged", "title": "Paged", "question": f"question-{index}"} for index in range(12)])
    set_browser_token(page, security.create_token("alice"))
    page.locator('[data-room="paged"]').click()
    expect(page.locator(".message.assistant")).to_have_count(5)
    expect(page.locator(".question")).to_be_enabled()
    assert page.locator(".message.user .message-text").all_text_contents() == [f"question-{index}" for index in range(7, 12)]

    anchor = page.locator(".message.user").first.evaluate("""node => {
        document.querySelector('.chat-body').scrollTo({ top: 0, behavior: 'instant' });
        return node.getBoundingClientRect().top;
    }""")
    page.locator(".chat-body").dispatch_event("wheel", {"deltaY": -100})
    expect(page.locator(".message.assistant")).to_have_count(10)
    expect(page.locator(".question")).to_be_enabled()
    if height == 720:
        position = page.locator(".message.user").filter(has_text="question-7").evaluate("node => node.getBoundingClientRect().top")
        assert abs(position - anchor) < 2
    page.locator(".chat-body").evaluate("pane => pane.scrollTop = 0")
    page.locator(".chat-body").dispatch_event("wheel", {"deltaY": -100})
    expect(page.locator(".message.assistant")).to_have_count(12)
    assert page.locator(".message.user .message-text").all_text_contents() == [f"question-{index}" for index in range(12)]

    requests = []
    page.on("request", lambda request: requests.append(request) if "before_id=" in request.url else None)
    page.locator(".chat-body").evaluate("pane => pane.scrollTop = 0")
    page.locator(".chat-body").dispatch_event("wheel", {"deltaY": -100})
    page.locator('[data-room="paged"]').click()
    expect(page.locator(".message.assistant")).to_have_count(5)
    assert not requests
    assert "question-" not in page.evaluate("localStorage.getItem('damda-chat-v1:user:alice')")


def test_history_page_failure_can_retry_without_clearing_current_messages(browser_page, database):
    from playwright.sync_api import expect

    page = browser_page
    seed_rooms(database, [{"id": "paged", "title": "Paged", "question": f"question-{index}"} for index in range(8)])
    set_browser_token(page, security.create_token("alice"))
    page.locator('[data-room="paged"]').click()
    expect(page.locator(".message.assistant")).to_have_count(5)
    page.route("**/api/me/chats?*before_id=*", lambda route: route.fulfill(status=503, json={"message": "조회 실패"}))
    page.locator(".chat-body").evaluate("pane => pane.scrollTop = 0")
    expect(page.locator(".status")).to_have_text("조회 실패")
    expect(page.locator(".message.assistant")).to_have_count(5)
    page.unroute("**/api/me/chats?*before_id=*")
    page.locator(".chat-body").dispatch_event("wheel", {"deltaY": -100})
    expect(page.locator(".message.assistant")).to_have_count(8)


def test_processing_refresh_keeps_expanded_history(browser_page, database, slow_ai):
    from playwright.sync_api import expect

    page = browser_page
    started, release, calls = slow_ai
    seed_rooms(database, [{"id": "paged", "title": "Paged", "question": f"question-{index}"} for index in range(8)])
    set_browser_token(page, security.create_token("alice"))
    page.locator('[data-room="paged"]').click()
    expect(page.locator(".message.assistant")).to_have_count(5)
    page.locator(".question").fill("new-question")
    page.locator(".send-button").click()
    assert started.wait(5)
    page.reload()
    expect(page.locator('.message.assistant[data-state="processing"]')).to_have_count(1)
    expect(page.locator(".message.assistant")).to_have_count(5)
    page.locator(".chat-body").evaluate("pane => pane.scrollTop = 0")
    expect(page.locator(".message.assistant")).to_have_count(9)
    release.set()
    expect(page.locator('.message.assistant[data-state="processing"]')).to_have_count(0, timeout=10000)
    expect(page.locator(".message.assistant")).to_have_count(9)
    assert page.locator(".message.user .message-text").all_text_contents() == [f"question-{index}" for index in range(8)] + ["new-question"]
    assert len(calls) == 1


def test_chat_retry_preserves_rooms_and_renders_plain_text(browser_page, database, ai_mock):
    from playwright.sync_api import expect

    page = browser_page
    rooms = [{"id": f"saved-{index}", "title": f"대화 {index}"} for index in range(30)]
    seed_rooms(database, rooms)
    set_browser_token(page, security.create_token("alice"))
    requests = []
    answer = '<img src=x onerror="window.chatInjected=true">'

    page.on("request", lambda request: requests.append(request.post_data_json) if request.method == "POST" and request.url.endswith("/api/chat") else None)

    async def reply(question, history, **kwargs):
        if len(requests) == 1:
            return AIResult(status="timeout", error_code=ErrorCode.TIMEOUT, request_id=kwargs["request_id"], model="test", latency_ms=1)
        return AIResult(status="success", answer=answer, request_id=kwargs["request_id"], model="test", latency_ms=1)

    ai_mock.side_effect = reply
    page.locator(".question").fill("재시도할 질문")
    page.locator(".send-button").click()
    expect(page.locator(".retry")).to_be_visible()
    expect(page.locator(".request-id")).to_be_hidden()
    expect(page.locator(".history-count")).to_have_text("31")
    expect(page.locator(".message.user .message-text")).to_have_text("재시도할 질문")
    expect(page.locator('.message.assistant[data-state="timeout"]')).to_have_count(1)
    page.reload()
    expect(page.locator('.message.assistant[data-state="timeout"]')).to_have_count(1)

    page.locator(".retry").click()
    success = page.locator('.message.assistant[data-state="success"]')
    expect(success.locator(".message-text")).to_have_text(answer)
    expect(page.locator(".message.user .copy-button").first).to_be_hidden()
    expect(page.locator(".message img")).to_have_count(0)
    expect(page.locator(".question")).to_have_value("")
    expect(page.locator(".history-count")).to_have_text("31")
    assert requests[0] == requests[1]
    saved = page.evaluate("JSON.parse(localStorage.getItem('damda-chat-v1:user:alice'))")
    assert saved[0]["id"] == requests[0]["room_id"]
    assert saved[1:] == list(reversed(rooms))[:29]
    assert all(set(room) == {"id", "title"} for room in saved)
    with database() as db:
        rows = db.query(ChatLog).filter_by(room_id=requests[0]["room_id"]).order_by(ChatLog.id).all()
        assert [row.status for row in rows] == ["timeout", "success"]

    page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {
        configurable: true, value: { writeText: async text => { window.copiedText = text; } }
    })""")
    success.locator(".copy-button").click()
    expect(page.locator(".toast")).to_have_text("답변을 복사했습니다.")
    assert page.evaluate("window.copiedText") == answer
    page.evaluate("() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })")
    success.locator(".copy-button").click()
    expect(page.locator(".fallback-copy")).to_have_value(answer)
    assert page.locator(".fallback-copy").evaluate("area => area.selectionEnd - area.selectionStart") == len(answer)


@pytest.fixture
def slow_ai(browser_page, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    async def answer(question, **kwargs):
        calls.append(question)
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return AIResult(status="success", answer="완료된 답변", request_id=kwargs["request_id"], model="test", latency_ms=1)

    monkeypatch.setattr(AI_connect, "generate_answer", answer)
    try:
        yield started, release, calls
    finally:
        release.set()


@pytest.mark.parametrize("action", ["reload", "stop", "account-change", "client-timeout"])
def test_processing_survives_browser_disconnect_and_finishes_once(browser_page, database, slow_ai, action):
    from playwright.sync_api import expect

    page = browser_page
    started, release, calls = slow_ai
    if action == "client-timeout":
        page.clock.install()
    token = security.create_token("alice")
    set_browser_token(page, token)
    page.locator(".question").fill("처리 중 질문")
    page.locator(".send-button").click()
    assert started.wait(5)
    with database() as db:
        row = db.query(ChatLog).one()
        chat_id, room_id = row.id, row.room_id
        assert (row.status, row.answer) == ("processing", None)
    expect(page.locator(".question")).to_be_disabled()
    expect(page.locator(".delete-chat")).to_be_disabled()
    expect(page.locator(".history-item")).to_be_enabled()

    if action == "reload":
        page.reload()
    elif action == "stop":
        page.locator(".stop-button").click()
        expect(page.locator(".status")).to_contain_text("중지")
        expect(page.locator(".message.user .message-text")).to_have_text("처리 중 질문")
        page.locator(".history-item").click()
    elif action == "account-change":
        set_browser_token(page, security.create_token("bob"))
        expect(page.locator(".header-user")).to_have_text("bob")
        expect(page.locator(".message")).to_have_count(0)
        expect(page.locator(".history-count")).to_have_text("0")
        set_browser_token(page, token)
        page.locator(".history-item").click()
    else:
        page.clock.fast_forward(30_001)

    expect(page.locator('.message.assistant[data-state="processing"]')).to_have_count(1)
    expect(page.locator(".status")).to_contain_text("생성하고")
    expect(page.locator(".retry")).to_be_hidden()
    release.set()
    expect(page.locator('.message.assistant[data-state="success"] .message-text')).to_have_text("완료된 답변", timeout=10_000)
    expect(page.locator(".question")).to_be_enabled()
    expect(page.locator('.message[data-state="processing"]')).to_have_count(0)
    assert calls == ["처리 중 질문"]
    with database() as db:
        row = db.query(ChatLog).one()
        assert (row.id, row.room_id, row.status, row.answer) == (chat_id, room_id, "success", "완료된 답변")
    assert page.evaluate("JSON.parse(localStorage.getItem('damda-chat-v1:user:alice'))") == [{"id": room_id, "title": "처리 중 질문"}]


def test_late_answer_does_not_change_another_room(browser_page, database, slow_ai):
    from playwright.sync_api import expect

    page = browser_page
    started, release, calls = slow_ai
    seed_rooms(database, [{"id": "other-room", "title": "다른 방"}])
    set_browser_token(page, security.create_token("alice"))
    page.locator(".question").fill("오래 걸리는 질문")
    page.locator(".send-button").click()
    assert started.wait(5)
    page.locator('[data-room="other-room"]').click()
    expect(page.locator(".message.assistant .message-text")).to_have_text("이전 답변")
    with page.expect_response("**/api/chat"):
        release.set()
    expect(page.locator(".conversation-title")).to_have_text("다른 방")
    expect(page.locator(".message.assistant .message-text")).to_have_text("이전 답변")
    page.locator(".history-item").filter(has_text="오래 걸리는 질문").click()
    expect(page.locator('.message.assistant[data-state="success"] .message-text')).to_have_text("완료된 답변")
    assert calls == ["오래 걸리는 질문"]


def test_lost_success_response_is_recovered_without_resending(browser_page, database, ai_mock):
    from playwright.sync_api import expect

    page = browser_page
    set_browser_token(page, security.create_token("alice"))

    def lose_response(route):
        assert route.fetch().status == 200
        route.abort("failed")

    page.route("**/api/chat", lose_response)
    page.locator(".question").fill("응답 유실 질문")
    page.locator(".send-button").click()
    expect(page.locator('.message.assistant[data-state="success"] .message-text')).to_have_text("테스트 답변")
    expect(page.locator(".status")).to_have_text("")
    expect(page.locator(".question")).to_have_value("")
    ai_mock.assert_awaited_once()
    with database() as db:
        assert db.query(ChatLog).one().status == "success"


def test_new_room_can_send_while_another_room_is_processing(browser_page, database, slow_ai):
    from playwright.sync_api import expect

    page = browser_page
    started, release, calls = slow_ai
    set_browser_token(page, security.create_token("alice"))
    page.locator(".question").fill("첫 번째 방 질문")
    page.locator(".send-button").click()
    assert started.wait(5)
    first_room = page.locator(".history-item.active").get_attribute("data-room")
    page.locator("[data-new]").first.click()
    page.locator(".question").fill("두 번째 방 질문")
    with page.expect_request("**/api/chat"):
        page.locator(".send-button").click()
    expect(page.locator(".history-count")).to_have_text("2")
    release.set()
    expect(page.locator('.message.assistant[data-state="success"] .message-text')).to_have_text("완료된 답변")
    expect(page.locator(".message.user .message-text")).to_have_text("두 번째 방 질문")
    page.locator('[data-room="' + first_room + '"]').click()
    expect(page.locator(".message.user .message-text")).to_have_text("첫 번째 방 질문")
    expect(page.locator('.message.assistant[data-state="success"] .message-text')).to_have_text("완료된 답변")
    assert calls == ["첫 번째 방 질문", "두 번째 방 질문"]
    with database() as db:
        rows = db.query(ChatLog).all()
        assert len(rows) == len({row.room_id for row in rows}) == 2
        assert all(row.status == "success" for row in rows)


@pytest.mark.parametrize("next_user", ["alice", "bob"])
def test_expired_chat_draft_returns_only_to_same_account(browser_page, database, next_user):
    from playwright.sync_api import expect

    page = browser_page
    rooms = [{"id": "saved-room", "title": "기존 대화", "messages": [{"role": "user", "text": "이전 질문"}]}]
    seed_rooms(database, rooms)
    seed_rooms(database, [{"id": f"newer-{index}", "title": f"다른 방 {index}"} for index in range(30)])
    page.evaluate("rooms => localStorage.setItem('damda-chat-v1:user:alice', JSON.stringify(rooms))", rooms)
    set_browser_token(page, security.create_token("alice"))
    page.locator(".history-item").filter(has_text="기존 대화").click()
    assert page.evaluate("JSON.parse(localStorage.getItem('damda-chat-v1:user:alice')).some(room => room.id === 'saved-room')") is False
    page.locator(".question").fill("작성 중인 질문")
    expired = jwt.encode({"id": "alice", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, security.KEY, algorithm="HS256")
    set_browser_token(page, expired)
    expect(page.locator(".header-user")).to_be_hidden()
    expect(page.locator(".question")).to_have_value("작성 중인 질문")
    expect(page.locator(".message")).to_have_count(0)

    set_browser_token(page, security.create_token(next_user))
    expect(page.locator(".header-user")).to_have_text(next_user)
    expect(page.locator(".question")).to_have_value("작성 중인 질문" if next_user == "alice" else "")
    expect(page.locator(".message")).to_have_count(2 if next_user == "alice" else 0)
    if next_user == "alice":
        expect(page.locator(".conversation-title")).to_have_text("기존 대화")


def test_chat_save_failure_keeps_successful_answer_visible(browser_page, ai_mock):
    from playwright.sync_api import expect

    page = browser_page
    set_browser_token(page, security.create_token("alice"))
    page.evaluate("""() => {
        const original = Storage.prototype.setItem;
        Storage.prototype.setItem = function(key, value) {
            if (key.startsWith('damda-chat-v1')) throw new Error('blocked');
            return original.call(this, key, value);
        };
    }""")
    page.locator(".question").fill("저장 실패 질문")
    page.locator(".send-button").click()
    expect(page.locator(".message.assistant .message-text")).to_have_text("테스트 답변")
    expect(page.locator(".question")).to_have_value("")
    expect(page.locator(".toast")).to_contain_text("저장하지 못했습니다")
    assert page.evaluate("JSON.parse(localStorage.getItem('damda-chat-v1:user:alice') || '[]')") == []


def set_browser_token(page, token):
    page.evaluate("""token => {
        localStorage.setItem('access_token', token);
        window.dispatchEvent(new StorageEvent('storage', {key: 'access_token'}));
    }""", token)


def test_completed_history_loads_across_browsers_and_deletes_from_server(browser_page, database, ai_mock):
    from playwright.sync_api import expect

    page = browser_page
    seed_rooms(database, [{"id": "server-room", "title": "서버 대화", "question": "서버 질문", "answer": "서버 답변"}])
    page.evaluate("""() => localStorage.setItem('damda-chat-v1:user:alice', JSON.stringify([
        {id: 'server-room', title: '낡은 제목', messages: [{role: 'assistant', text: '브라우저에만 있는 답변'}]}
    ]))""")
    token = security.create_token("alice")
    set_browser_token(page, token)
    page.locator(".history-item").filter(has_text="서버 대화").click()
    expect(page.locator(".message.assistant .message-text")).to_have_text("서버 답변")
    assert page.evaluate("JSON.parse(localStorage.getItem('damda-chat-v1:user:alice'))") == [{"id": "server-room", "title": "서버 대화"}]

    context = page.context.browser.new_context()
    try:
        other = context.new_page()
        other.goto(page.url)
        assert other.evaluate("localStorage.getItem('damda-chat-v1:user:alice')") is None
        set_browser_token(other, token)
        other.locator(".history-item").click()
        expect(other.locator(".message.assistant .message-text")).to_have_text("서버 답변")
        ai_mock.assert_not_called()

        other.locator(".question").fill("다른 브라우저 질문")
        other.locator(".send-button").click()
        expect(other.locator(".message.assistant .message-text")).to_have_text(["서버 답변", "테스트 답변"])
        expect(other.locator(".send-button")).to_be_enabled()
        ai_mock.assert_awaited_once()

        page.locator(".history-item").click()
        expect(page.locator(".message.user .message-text")).to_have_text(["서버 질문", "다른 브라우저 질문"])
        expect(page.locator(".send-button")).to_be_enabled()
        for current in (page, other):
            assert current.evaluate("JSON.parse(localStorage.getItem('damda-chat-v1:user:alice'))") == [{"id": "server-room", "title": "서버 대화"}]

        with other.expect_response(lambda reply: reply.request.method == "DELETE") as removed:
            other.locator(".delete-chat").click()
        assert removed.value.json() == {"deleted": 2}
        expect(other.locator(".history-count")).to_have_text("0")
        with database() as db:
            assert db.query(ChatLog).count() == 0
        page.reload()
        expect(page.locator(".send-button")).to_be_enabled()
        expect(page.locator(".history-count")).to_have_text("0")
        expect(page.locator(".message")).to_have_count(0)
    finally:
        context.close()


def test_failed_history_and_delete_do_not_use_local_messages_or_remove_room(browser_page, database):
    from playwright.sync_api import expect

    page = browser_page
    seed_rooms(database, [{"id": "server-room", "title": "서버 대화"}])
    page.evaluate("""() => localStorage.setItem('damda-chat-v1:user:alice', JSON.stringify([
        {id: 'server-room', title: '서버 대화', messages: [{role: 'assistant', text: '오래된 답변'}]}
    ]))""")
    page.route("**/api/me/chats?*", lambda route: route.fulfill(status=503, json={"message": "조회 실패"}))
    set_browser_token(page, security.create_token("alice"))
    page.locator(".history-item").click()
    expect(page.locator(".status")).to_have_text("조회 실패")
    expect(page.locator(".message")).to_have_count(0)
    page.unroute("**/api/me/chats?*")
    page.locator(".history-item").click()
    expect(page.locator(".message.assistant .message-text")).to_have_text("이전 답변")
    page.route("**/api/me/chats?*", lambda route: route.fulfill(status=503, json={"message": "삭제 실패"}))
    page.locator(".delete-chat").click()
    expect(page.locator(".status")).to_have_text("삭제 실패")
    expect(page.locator(".history-count")).to_have_text("1")
    expect(page.locator(".message.assistant .message-text")).to_have_text("이전 답변")
    with database() as db:
        assert db.query(ChatLog).count() == 1


@pytest.mark.parametrize("next_view", ["room", "account"])
def test_late_history_does_not_replace_new_room_or_account(browser_page, database, next_view):
    from playwright.sync_api import expect

    page = browser_page
    seed_rooms(database, [{"id": "room-a", "title": "방 A"}, {"id": "room-b", "title": "방 B"}])
    set_browser_token(page, security.create_token("alice"))
    held = []
    page.route("**/api/me/chats?room_id=room-a", lambda route: held.append(route))
    with page.expect_request("**/api/me/chats?room_id=room-a"):
        page.locator(".history-item").filter(has_text="방 A").click()
    if next_view == "room":
        page.locator(".history-item").filter(has_text="방 B").click()
        expect(page.locator(".conversation-title")).to_have_text("방 B")
        expect(page.locator(".message.assistant .message-text")).to_have_text("이전 답변")
    else:
        set_browser_token(page, security.create_token("bob"))
        expect(page.locator(".header-user")).to_have_text("bob")
        expect(page.locator(".history-count")).to_have_text("0")
    held[0].fulfill(json=[{"question": "늦은 질문", "answer": "다른 화면에 나오면 안 되는 답변"}])
    expect(page.locator(".send-button")).to_be_enabled()
    expect(page.locator(".message.assistant .message-text")).to_have_text(["이전 답변"] if next_view == "room" else [])


def test_history_failure_after_success_does_not_resend_question(browser_page, database, ai_mock):
    from playwright.sync_api import expect

    page = browser_page
    set_browser_token(page, security.create_token("alice"))
    expect(page.locator(".send-button")).to_be_enabled()
    page.route("**/api/me/rooms", lambda route: route.fulfill(status=503, json={"message": "목록 조회 실패"}))
    page.locator(".question").fill("저장된 질문")
    page.locator(".send-button").click()
    expect(page.locator(".status")).to_have_text("목록 조회 실패")
    expect(page.locator(".message.assistant .message-text")).to_have_text("테스트 답변")
    expect(page.locator(".retry")).to_be_hidden()
    expect(page.locator(".question")).to_have_value("")
    ai_mock.assert_awaited_once()
    with database() as db:
        assert db.query(ChatLog).one().question == "저장된 질문"


def test_initial_room_list_replaces_local_metadata_before_selection(browser_page, database):
    from playwright.sync_api import expect

    page = browser_page
    seed_rooms(database, [{"id": "server-room", "title": "서버 대화"}])
    page.evaluate("""() => localStorage.setItem('damda-chat-v1:user:alice', JSON.stringify([
        {id: 'old-room', title: '이전 목록'}
    ]))""")
    held = []
    page.route("**/api/me/rooms", lambda route: held.append(route))
    with page.expect_request("**/api/me/rooms"):
        set_browser_token(page, security.create_token("alice"))
    expect(page.locator(".history-item")).to_have_text("이전 목록")
    expect(page.locator(".history-item")).to_be_disabled()
    held[0].fulfill(json=[{"room_id": "server-room", "room_name": "서버 대화"}])
    page.locator(".history-item").filter(has_text="서버 대화").click()
    expect(page.locator(".message.assistant .message-text")).to_have_text("이전 답변")


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
    elif kind == "unauthorized":
        with page.expect_response("**/api/me/rooms") as reply:
            set_browser_token(page, token)
        assert reply.value.status == 401
        expect(page.locator("#status")).to_contain_text("로그인")
    else:
        set_browser_token(page, token)
        expect(page.locator("#header-user")).to_have_text(user_id)
        if kind == "expires-idle":
            page.clock.fast_forward(61_000)

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
    expect(page.locator("#status")).to_have_text("AI 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.")
    expect(page.locator("#header-user")).to_have_text("alice")
    assert page.evaluate("localStorage.getItem('access_token')") == token
    call.assert_awaited_once()
    with database() as db:
        row = db.query(ChatLog).one()
        assert (row.status, row.error_code, row.answer) == ("error", code, None)


@pytest.mark.parametrize("mode", ["login", "signup"])
def test_auth_form_uses_same_limits(browser_page, mode):
    from playwright.sync_api import expect

    page = browser_page
    requests = []
    user_id = "🙂" * 50
    page.route("**/auth/*", lambda route: route.fulfill(json={"token": security.create_token(user_id)}))
    page.route("**/api/me/rooms", lambda route: route.fulfill(json=[]))
    page.on("request", lambda request: requests.append(request) if "/auth/" in request.url else None)
    page.locator(".login-button").click()
    page.locator(f'[data-tab="{mode}"]').click()
    if mode == "signup":
        page.locator(".auth-confirm").fill("test-only-123")
    else:
        expect(page.locator(".auth-password")).to_have_attribute("placeholder", "비밀번호를 입력하세요")
        page.locator(".auth-submit").click()
        expect(page.locator(".auth-status")).to_have_text("로그인에 실패했습니다.")

    for name, password, message in [
        ("ab", "test-only-123", "3~50자"),
        ("🙂🙂", "test-only-123", "3~50자"),
        ("a" * 51, "test-only-123", "3~50자"),
        ("valid-id", "1234567", "8자 이상"),
        ("valid-id", "🙂" * 7, "8자 이상"),
        ("valid-id", " " * 8, "비밀번호를 입력"),
        ("valid-id", "가" * 25, "비밀번호가 너무 깁니다"),
        ("valid-id", "a" * 73, "비밀번호가 너무 깁니다"),
    ]:
        page.locator(".auth-name").fill(name)
        page.locator(".auth-password").fill(password)
        page.locator(".auth-submit").click()
        expect(page.locator(".auth-status")).to_contain_text(message if mode == "signup" else "로그인에 실패했습니다.")
    assert not requests

    page.locator(".auth-name").fill(f" {user_id} ")
    page.locator(".auth-password").fill("가" * 24)
    if mode == "signup":
        page.locator(".auth-confirm").fill("가" * 24)
    page.locator(".auth-submit").click()
    expect(page.locator(".header-user")).to_have_text(user_id)
    expect(page.locator(".auth-dialog")).not_to_be_visible()
    assert len(requests) == 1
    assert requests[0].url.endswith("/auth/register" if mode == "signup" else "/auth/login")
    assert requests[0].post_data_json == {"id": user_id, "pw": "가" * 24}


def test_signup_auto_login_validation_and_reload(browser_page, database):
    from playwright.sync_api import expect

    page = browser_page
    requests = []
    page.on("request", lambda request: requests.append(request) if "/auth/" in request.url else None)
    page.locator(".login-button").click()
    page.locator('[data-tab="signup"]').click()
    page.locator(".auth-name").fill("ab")
    page.locator(".auth-password").fill("short")
    page.locator(".auth-confirm").fill("short")
    page.locator(".auth-submit").click()
    expect(page.locator(".auth-status")).to_contain_text("3~50자")
    page.locator(".auth-name").fill("새사용자")
    page.locator(".auth-submit").click()
    expect(page.locator(".auth-status")).to_contain_text("8자 이상")
    page.locator(".auth-password").fill("test-only-123")
    page.locator(".auth-submit").click()
    expect(page.locator(".auth-status")).to_contain_text("서로 다릅니다")
    assert not requests

    page.locator(".auth-name").fill(" 새사용자 ")
    page.locator(".auth-confirm").fill("test-only-123")
    with page.expect_response("**/auth/register") as response:
        page.locator(".auth-submit").click()
    assert response.value.status == 200
    expect(page.locator(".header-user")).to_have_text("새사용자")
    expect(page.locator(".auth-dialog")).not_to_be_visible()
    assert page.evaluate("localStorage.getItem('access_token')") == response.value.json()["token"]
    assert len(requests) == 1
    assert requests[0].url.endswith("/auth/register")
    page.reload()
    expect(page.locator(".header-user")).to_have_text("새사용자")
    with database() as db:
        assert security.verify_password("test-only-123", db.get(Login, "새사용자").pw)

    page.locator(".login-button").click()
    expect(page.locator(".header-user")).to_be_hidden()
    page.locator(".login-button").click()
    expect(page.locator(".auth-name")).to_have_value("")
    expect(page.locator(".auth-password")).to_have_value("")
    page.locator(".auth-name").fill("새사용자")
    page.locator(".auth-password").fill("wrong-password")
    with page.expect_response("**/auth/login") as response:
        page.locator(".auth-submit").click()
    assert response.value.status == 401
    expect(page.locator(".auth-status")).to_have_text("로그인에 실패했습니다.")
    expect(page.locator(".auth-submit")).to_be_enabled()
    page.locator(".auth-password").fill("test-only-123")
    page.locator(".auth-submit").click()
    expect(page.locator(".header-user")).to_have_text("새사용자")
    expect(page.locator(".auth-dialog")).not_to_be_visible()
    page.reload()
    expect(page.locator(".header-user")).to_have_text("새사용자")
    page.locator(".login-button").click()
    expect(page.locator(".header-user")).to_be_hidden()
    assert page.evaluate("localStorage.getItem('access_token')") is None


@pytest.mark.parametrize("action", ["close", "account-change"])
def test_pending_login_is_cancelled_on_close_or_account_change(browser_page, action):
    from playwright.sync_api import expect

    page = browser_page
    page.route("**/auth/login", lambda route: None)
    page.locator(".login-button").click()
    page.locator(".auth-name").fill("alice")
    page.locator(".auth-password").fill("test-only-123")
    with page.expect_request("**/auth/login"):
        page.locator(".auth-submit").click()
    expect(page.locator(".auth-submit")).to_be_disabled()

    with page.expect_event("requestfailed", predicate=lambda request: "/auth/login" in request.url):
        if action == "close":
            page.locator("[data-close]").click()
        else:
            set_browser_token(page, security.create_token("bob"))
    if action == "close":
        assert page.evaluate("localStorage.getItem('access_token')") is None
        page.locator(".login-button").click()
        expect(page.locator(".auth-status")).to_have_text("")
    else:
        expect(page.locator(".header-user")).to_have_text("bob")
    expect(page.locator(".auth-submit")).to_be_enabled()


def test_auth_storage_failures_show_error_without_retaining_login(browser_page):
    from playwright.sync_api import expect

    page = browser_page
    token = security.create_token("alice")
    page.route("**/auth/login", lambda route: route.fulfill(json={"token": token}))
    page.evaluate("""() => {
        const original = Storage.prototype.setItem;
        Storage.prototype.setItem = function(key, value) {
            if (key === 'access_token') throw new Error('blocked');
            return original.call(this, key, value);
        };
    }""")
    page.locator(".login-button").click()
    page.locator(".auth-name").fill("alice")
    page.locator(".auth-password").fill("test-only-123")
    page.locator(".auth-submit").click()
    expect(page.locator(".auth-status")).to_have_text("서버 상태가 좋지 않습니다. 잠시 후 다시 시도해 주세요.")
    expect(page.locator(".auth-submit")).to_be_enabled()
    expect(page.locator(".header-user")).to_be_hidden()
    assert page.evaluate("localStorage.getItem('access_token')") is None

    page.reload()
    set_browser_token(page, token)
    page.evaluate("""() => {
        Storage.prototype.removeItem = () => { throw new Error('blocked'); };
    }""")
    page.locator(".login-button").click()
    expect(page.locator(".header-user")).to_be_hidden()
    expect(page.locator(".toast")).to_contain_text("로그인 정보를 삭제하지 못했습니다")
    assert page.evaluate("localStorage.getItem('access_token')") == token
    page.locator("#question").fill("로그아웃 후 질문")
    page.locator("#send").click()
    expect(page.locator("#status")).to_contain_text("로그인")
    page.locator(".login-button").click()
    page.locator(".auth-name").fill("alice")
    page.locator(".auth-password").fill("test-only-123")
    page.locator(".auth-submit").click()
    expect(page.locator(".header-user")).to_have_text("alice")
    expect(page.locator(".auth-dialog")).not_to_be_visible()


@pytest.mark.parametrize("kind", [401, 422, 429, 500, 503, "network", "timeout", "invalid-json", "invalid-token"])
def test_login_shows_only_public_error_messages(browser_page, kind):
    from playwright.sync_api import expect

    page = browser_page

    def reply(route):
        if isinstance(kind, int):
            route.fulfill(status=kind, json={"message": "private-error UTF-8 72바이트"})
        elif kind == "network":
            route.abort()
        elif kind == "invalid-json":
            route.fulfill(status=200, body="private-error")
        elif kind == "invalid-token":
            route.fulfill(json={"token": "broken"})

    page.route("**/auth/login", reply)
    if kind == "timeout":
        page.clock.install()
    page.locator(".login-button").click()
    page.locator(".auth-name").fill("alice")
    page.locator(".auth-password").fill("test-only-123")
    with page.expect_request("**/auth/login"):
        page.locator(".auth-submit").click()
    if kind == "timeout":
        page.clock.fast_forward(30_001)

    message = "로그인에 실패했습니다." if kind in (401, 422) else "서버 상태가 좋지 않습니다. 잠시 후 다시 시도해 주세요."
    expect(page.locator(".auth-status")).to_have_text(message)
    expect(page.locator(".auth-submit")).to_be_enabled()
    expect(page.locator(".header-user")).to_be_hidden()
    assert page.evaluate("localStorage.getItem('access_token')") is None
