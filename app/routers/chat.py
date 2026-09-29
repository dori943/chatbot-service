from fastapi                import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies  import get_token_id
from app.schemas.chat       import ChatRequest
from app.db                 import get_db
from app.services           import chat_main

router = APIRouter(prefix="/api", tags=["chat"])


# API 라우팅: "/chat" 경로의 POST 요청을 처리
@router.post("/chat")
# 비동기(Async) 핸들러 함수 정의
async def send_chat(
    # 1. Request Body 검증: Pydantic 모델(ChatRequest)을 통한 데이터 유효성 검사
    data    : ChatRequest,
    # 2. 의존성 주입(Dependency Injection): 인증 토큰 검증 및 사용자 ID 추출
    user_id : str          = Depends(get_token_id),
    # 3. 의존성 주입: 비동기 데이터베이스 세션 획득
    db      : AsyncSession = Depends(get_db),
):
    # 컨트롤러(라우터) 역할만 수행하며, 실제 비즈니스 로직은 Service 레이어(chat_main)로 위임
    return await chat_main.chat(data, user_id, db)


@router.get("/me/chats")
async def get_my_chat(
    user_id : str          = Depends(get_token_id),
    db      : AsyncSession = Depends(get_db),
):
    return await chat_main.get_my_chat(user_id, db)
