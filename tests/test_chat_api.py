from datetime           import datetime
from uuid               import uuid4

from app.models.chatlog import ChatLog
from app.utils          import security


def test_home_and_openapi_start(client):
    assert client.get("/").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/chat", "/api/me/chats", "/auth/login", "/auth/register"} <= paths.keys()


def test_auth_required_before_ai(client, ai_mock):
    assert client.post("/api/chat", json={"question": "hi"}).status_code == 401
    assert client.get("/api/me/chats").status_code == 401
    ai_mock.assert_not_called()


def test_history_is_owned_and_ordered_without_pagination(client, database, auth_headers, ai_mock):
    for question in ("first", "second"):
        assert client.post("/api/chat", json={"question": question}, headers=auth_headers).status_code == 200
    bob_headers = {"Authorization": f"Bearer {security.create_token('bob')}"}
    assert client.post("/api/chat", json={"question": "bob-private"}, headers=bob_headers).status_code == 200
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


def test_context_contains_only_own_successful_turns_in_chronological_order(client, database, auth_headers, ai_mock):
    with database() as db:
        rows = [
            ChatLog(
                user_id  = "alice",
                question = "first",
                answer   = "first answer",
                status   = "success",
            ),
            ChatLog(
                user_id  = "bob",
                question = "private",
                answer   = "private answer",
                status   = "success",
            ),
            ChatLog(
                user_id    = "alice",
                question   = "failed",
                status     = "error",
                error_code = "AI_TIMEOUT",
            ),
            ChatLog(
                user_id  = "alice",
                question = "second",
                answer   = "second answer",
                status   = "success",
            ),
        ]
        for row in rows:
            row.request_id = uuid4().hex
            row.created_at = datetime(2026, 1, 1)
        db.add_all(rows)
        db.commit()
    response = client.post("/api/chat", json={"question": " next "}, headers=auth_headers)
    assert response.status_code == 200
    assert ai_mock.call_args.kwargs["question"] == "next"
    assert ai_mock.call_args.kwargs["history"] == [
        {"question": "first", "answer": "first answer"},
        {"question": "second", "answer": "second answer"},
    ]


def test_failed_answer_appears_in_history(client, auth_headers, ai_mock):
    ai_mock.side_effect = RuntimeError("provider-down")
    assert client.post("/api/chat", json={"question": "failed"}, headers=auth_headers).status_code == 502
    row = client.get("/api/me/chats", headers=auth_headers).json()[0]
    assert (row["question"], row["status"], row["answer"]) == ("failed", "error", None)
