"""채팅 API 요청/응답 스키마.

프론트·백엔드와 공유하는 '계약'이다. 바꿀 때는 반드시 팀에 공유할 것.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """POST /api/chat 요청 본문."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="사용자 질문. 앞뒤 공백은 제거되며 빈 문자열은 거부된다.",
    )

    @field_validator("question")
    @classmethod
    def strip_and_check(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("질문을 입력해 주세요.")
        return cleaned

    model_config = {
        "json_schema_extra": {
            "examples": [{"question": "FastAPI 배포 방법 알려줘"}]
        }
    }


class ChatResponse(BaseModel):
    """POST /api/chat 성공 응답 (HTTP 200)."""

    answer: str
    request_id: str
    created_at: datetime

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "answer": "FastAPI는 uvicorn으로 실행하며 ...",
                "request_id": "a1b2c3d4e5f6",
                "created_at": "2026-09-21T04:12:33Z",
            }]
        }
    }


class ErrorResponse(BaseModel):
    """실패 응답. 프론트는 error_code 로 분기하고 message 를 그대로 표시한다."""

    error_code: str = Field(..., description="AI_TIMEOUT, INVALID_INPUT 등")
    message: str = Field(..., description="사용자에게 보여줄 한국어 안내 문구")
    request_id: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "error_code": "AI_TIMEOUT",
                "message": "현재 응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
                "request_id": "a1b2c3d4e5f6",
            }]
        }
    }


class ChatLogItem(BaseModel):
    """GET /api/me/chats 응답의 각 항목."""

    id: int
    question: str
    answer: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatLogListResponse(BaseModel):
    """GET /api/me/chats 응답."""

    items: list[ChatLogItem]
    total: int
