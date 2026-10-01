from datetime               import datetime, timedelta, timezone
from uuid                   import uuid4
from unittest.mock          import AsyncMock

import pytest
from sqlalchemy.exc         import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chatlog     import ChatLog
from app.core               import config
from app.utils              import security


def test_home_and_openapi_start(client):
    assert client.get("/").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/chat", "/api/me/chats", "/auth/login", "/auth/register"} <= paths.keys()


def test_auth_required_before_ai(client, ai_mock):
    assert client.post("/api/chat", json={"room_id": "room-a", "room_name": "Test room", "question": "hi"}).status_code == 401
    assert client.get("/api/me/chats").status_code == 401
    assert client.get("/api/me/rooms").status_code == 401
    assert client.delete("/api/me/chats?room_id=room-a").status_code == 401
    ai_mock.assert_not_called()


def test_history_is_owned_and_ordered_without_pagination(client, database, auth_headers, ai_mock):
    for question in ("first", "second"):
        assert client.post("/api/chat", json={"room_id": "room-a", "room_name": "Test room", "question": question}, headers=auth_headers).status_code == 200
    bob_headers = {"Authorization": f"Bearer {security.create_token('bob')}"}
    assert client.post("/api/chat", json={"room_id": "room-a", "room_name": "Test room", "question": "bob-private"}, headers=bob_headers).status_code == 200
    # 같은 저장시각이라도 id 역순으로 일관되게 반환한다.
    with database() as db:
        for row in db.query(ChatLog):
            row.created_at = datetime(2026, 1, 1)
        db.commit()
    response = client.get("/api/me/chats?user_id=bob", headers=auth_headers)
    assert response.status_code == 200
    assert [item["question"] for item in response.json()] == ["second", "first"]
    assert "bob-private" not in response.text
    assert [item["question"] for item in client.get(
        "/api/me/chats",
        headers = bob_headers,
    ).json()] == ["bob-private"]


def test_context_contains_only_own_room_successful_turns_in_chronological_order(client, database, auth_headers, ai_mock):
    with database() as db:
        rows = [
            ChatLog(
                room_id    = "room-a",
                room_name  = "Test room",
                user_id    = "alice",
                question   = "first",
                answer     = "first answer",
                status     = "success",
            ),
            ChatLog(
                room_id    = "room-a",
                room_name  = "Test room",
                user_id    = "bob",
                question   = "private",
                answer     = "private answer",
                status     = "success",
            ),
            ChatLog(
                room_id    = "room-a",
                room_name  = "Test room",
                user_id    = "alice",
                question   = "failed",
                status     = "error",
                error_code = "AI_TIMEOUT",
            ),
            ChatLog(
                room_id    = "room-a",
                room_name  = "Test room",
                user_id    = "alice",
                question   = "second",
                answer     = "second answer",
                status     = "success",
            ),
        ]
        rows.append(ChatLog(
            user_id    = "alice",
            room_id    = "room-b",
            room_name  = "Test room",
            question   = "other room",
            answer     = "other room answer",
            status     = "success",
        ))
        for row in rows:
            row.request_id = uuid4().hex
            row.created_at = datetime(2026, 1, 1)
        db.add_all(rows)
        db.commit()
    response = client.post("/api/chat", json={"room_id": "room-a", "room_name": "Test room", "question": " next "}, headers=auth_headers)
    assert response.status_code == 200
    assert ai_mock.call_args.kwargs["question"] == "next"
    assert ai_mock.call_args.kwargs["history"] == [
        {"question": "first", "answer": "first answer"},
        {"question": "second", "answer": "second answer"},
    ]
    assert response.json()["room_id"] == "room-a"
    with database() as db:
        assert db.query(ChatLog).filter_by(question="next").one().room_id == "room-a"


def test_failed_answer_appears_in_history(client, auth_headers, ai_mock):
    ai_mock.side_effect = RuntimeError("provider-down")
    assert client.post("/api/chat", json={"room_id": "room-a", "room_name": "Test room", "question": "failed"}, headers=auth_headers).status_code == 502
    row = client.get("/api/me/chats", headers=auth_headers).json()[0]
    assert (row["question"], row["status"], row["answer"]) == ("failed", "error", None)
    assert row["room_id"] == "room-a"
    assert row["room_name"] == "Test room"


def test_room_history_pages_remain_stable_when_new_questions_arrive(client, database, auth_headers):
    with database() as db:
        for index in range(12):
            db.add(ChatLog(user_id="alice", room_id="room-a", room_name="Room", question=str(index),
                           status="success", request_id=uuid4().hex, created_at=datetime(2026, 1, 1)))
        db.flush()
        ids = [row.id for row in db.query(ChatLog).order_by(ChatLog.id.desc())]
        for user, room in [("bob", "room-a"), ("alice", "room-b")]:
            db.add(ChatLog(user_id=user, room_id=room, room_name="Private", question="private",
                           status="success", request_id=uuid4().hex, created_at=datetime(2026, 1, 1)))
        db.commit()

    first = client.get("/api/me/chats?room_id=room-a", headers=auth_headers).json()
    assert [row["id"] for row in first] == ids[:5]
    with database() as db:
        db.add(ChatLog(user_id="alice", room_id="room-a", room_name="Room", question="new",
                       status="processing", request_id=uuid4().hex, created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        db.commit()

    collected = first[:]
    for expected in [ids[5:10], ids[10:], []]:
        response = client.get("/api/me/chats", params={"room_id": "room-a", "before_id": collected[-1]["id"]}, headers=auth_headers)
        assert response.status_code == 200
        page = response.json()
        assert [row["id"] for row in page] == expected
        collected.extend(page)
    assert [row["id"] for row in collected] == ids
    assert len(client.get("/api/me/chats", headers=auth_headers).json()) == 14
    assert client.get("/api/me/chats?room_id=room-a", headers=auth_headers).json()[0]["status"] == "processing"


@pytest.mark.parametrize("params", [
    {"room_id": "room-a", "before_id": 0},
    {"room_id": "room-a", "before_id": -1},
    {"room_id": "room-a", "before_id": 9223372036854775808},
    {"room_id": "room-a", "before_id": "invalid"},
    {"before_id": 5},
])
def test_history_rejects_invalid_cursor(client, auth_headers, params):
    response = client.get("/api/me/chats", params=params, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_INPUT"


def test_room_list_history_and_delete_are_owned(client, database, auth_headers):
    with database() as db:
        for user, room, name, question, status in [
            ("alice", "room-a", "처음 이름", "first", "success"),
            ("alice", "room-b", "다른 방", "other-room", "success"),
            ("alice", "room-a", "최근 이름", "second", "success"),
            ("alice", "room-a", "실패 요청 이름", "failed", "error"),
            ("alice", "failed-room", "실패한 방", "failed-only", "timeout"),
            ("bob", "room-a", "비공개 방", "bob-private", "success"),
        ]:
            db.add(ChatLog(
                user_id=user, room_id=room, room_name=name, question=question,
                answer=f"{question} answer" if status == "success" else None,
                status=status, request_id=uuid4().hex, created_at=datetime(2026, 1, 1),
            ))
        db.commit()

    rooms = client.get("/api/me/rooms?user_id=bob", headers=auth_headers)
    assert rooms.status_code == 200
    assert rooms.json() == [
        {"room_id": "failed-room", "room_name": "실패한 방"},
        {"room_id": "room-a", "room_name": "실패 요청 이름"},
        {"room_id": "room-b", "room_name": "다른 방"},
    ]
    rows = client.get("/api/me/chats?room_id=room-a&user_id=bob", headers=auth_headers).json()
    assert [row["question"] for row in rows] == ["failed", "second", "first"]
    assert client.get("/api/me/chats?room_id=missing", headers=auth_headers).json() == []

    response = client.delete("/api/me/chats?room_id=room-a&user_id=bob", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"deleted": 3}
    assert client.delete("/api/me/chats?room_id=room-a", headers=auth_headers).json() == {"deleted": 0}
    assert client.get("/api/me/chats?room_id=room-a", headers=auth_headers).json() == []
    with database() as db:
        assert db.query(ChatLog).filter_by(user_id="alice", room_id="room-a").count() == 0
        assert db.query(ChatLog).filter_by(user_id="bob", room_id="room-a").one().question == "bob-private"
        assert db.query(ChatLog).filter_by(user_id="alice").count() == 2


@pytest.mark.parametrize("method", ["get", "delete"])
@pytest.mark.parametrize("room_id", ["", "  ", "a" * 65])
def test_room_requests_reject_invalid_id(client, auth_headers, method, room_id):
    response = getattr(client, method)("/api/me/chats", params={"room_id": room_id}, headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.parametrize("method,path", [("get", "/api/me/rooms"), ("delete", "/api/me/chats?room_id=room-a")])
def test_room_database_errors_are_reported(client, auth_headers, monkeypatch, method, path):
    monkeypatch.setattr(AsyncSession, "execute", AsyncMock(side_effect=SQLAlchemyError("private-sql")))
    rollback = AsyncMock()
    monkeypatch.setattr(AsyncSession, "rollback", rollback)
    response = getattr(client, method)(path, headers=auth_headers)
    assert response.status_code == 503
    assert response.json()["error_code"] == "DB_UNAVAILABLE"
    assert "private-sql" not in response.text
    rollback.assert_awaited()


@pytest.mark.parametrize("path", ["/api/me/chats?room_id=old", "/api/me/rooms"])
def test_abandoned_processing_expires_only_for_current_user(client, database, auth_headers, ai_mock, path):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with database() as db:
        for user, room, status, created_at in [
            ("alice", "old", "processing", now - timedelta(seconds=config.AI_TOTAL_TIMEOUT_SECONDS + 31)),
            ("alice", "current", "processing", now),
            ("alice", "done", "success", now - timedelta(days=1)),
            ("bob", "old", "processing", now - timedelta(days=1)),
        ]:
            db.add(ChatLog(user_id=user, room_id=room, room_name=room, question="question",
                           status=status, request_id=uuid4().hex, created_at=created_at))
        db.commit()
    assert client.get(path, headers=auth_headers).status_code == 200
    with database() as db:
        row = db.query(ChatLog).filter_by(user_id="alice", room_id="old").one()
        assert (row.status, row.error_code) == ("error", "INTERNAL_ERROR")
        assert db.query(ChatLog).filter_by(user_id="alice", room_id="current").one().status == "processing"
        assert db.query(ChatLog).filter_by(user_id="alice", room_id="done").one().status == "success"
        assert db.query(ChatLog).filter_by(user_id="bob").one().status == "processing"
    ai_mock.assert_not_called()
