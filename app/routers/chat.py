from fastapi                import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies  import get_token_id
from app.schemas.chat       import ChatRequest
from app.db                 import get_db
# 파이썬 모듈 시스템: 다른 폴더(app/services)에 있는 chat_main.py 파일을 가져와 참조함
from app.services           import chat_main

# URL 접두어(prefix)를 /api로 설정하여, 이 라우터 안의 모든 주소는 /api로 시작됨
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


# RESTful API 관례: '/me'는 현재 로그인한 인증된 사용자를 의미함
# 즉, 현재 로그인한 사용자의 과거 채팅 내역(chats) 전체를 조회하는 GET 요청 엔드포인트
@router.get("/me/chats")
async def get_my_chat(
    # 프레임워크가 토큰 검사 로직(get_token_id)을 사전 실행하여 user_id에 주입
    user_id : str          = Depends(get_token_id),
    # 트랜잭션이 관리되는 DB 세션 객체를 db 변수에 주입
    db      : AsyncSession = Depends(get_db),
):
    # 비즈니스 로직(조회 쿼리 수행)을 Service 레이어로 위임
    return await chat_main.get_my_chat(user_id, db)

