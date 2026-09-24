"""실제 Gemini 호출은 RUN_LIVE_AI=1, 전용 MySQL 설정이 모두 있을 때만 실행한다."""
import os

import pytest

from app.services import AI_connect

pytestmark = [
    pytest.mark.live_ai,
    pytest.mark.skipif(os.getenv("RUN_LIVE_AI") != "1", reason="실제 AI 호출은 RUN_LIVE_AI=1로 명시 실행"),
]


def test_live_ai_answer_is_saved_and_readable(client, auth_headers):
    assert AI_connect.AI_API_KEY, "AI_API_KEY가 필요합니다."
    response = client.post("/api/chat", json={"question": "안녕하세요라고 한 문장으로 답해 주세요."}, headers=auth_headers)
    assert response.status_code == 200, f"status={response.status_code}, code={response.json().get('error_code')}"
    assert response.json()["answer"].strip()
    history = client.get("/api/me/chats", headers=auth_headers).json()
    assert len(history) == 1
    assert history[0]["answer"] == response.json()["answer"]
