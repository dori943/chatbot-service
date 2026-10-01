from fastapi                import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth      import login, register
from app.schemas.auth       import AuthRequest
from app.db                 import get_db

# 인증 관련 API 경로의 공통 접두사(/auth) 및 Swagger 태그 설정
router = APIRouter(prefix="/auth", tags=["auth"])


# ==============================================================================
# [로그인 엔드포인트: /auth/login]
# 클라이언트로부터 아이디/비밀번호를 수신하여 자격증명을 검증하고 JWT 액세스 토큰 반환
# 1) 입력 유효성 자동 검증: Pydantic AuthRequest 스키마를 통해 JSON 바디의 id, pw 필드 타입 검사
# 2) DB 세션 주입: FastAPI 의존성 주입(Depends(get_db))으로 안전한 비동기 세션 생명주기 관리
# 3) 서비스 위임: 실제 인증 검증 및 토큰 발급은 auth.login() 서비스 함수로 위임
# ==============================================================================
# 사용자 로그인 처리를 위한 HTTP POST 라우트 핸들러
@router.post("/login")
async def login_route(
    # 클라이언트가 전송한 JSON 요청 본문 (Pydantic DTO 자동 역직렬화)
    data : AuthRequest,
    # 의존성 주입을 통해 할당받은 비동기 데이터베이스 세션
    db   : AsyncSession = Depends(get_db),
):
    # 비즈니스 계층의 login 서비스 함수로 인증 처리 및 토큰 발급 위임
    return await login(data, db)


# ==============================================================================
# [회원가입 엔드포인트: /auth/register]
# 신규 사용자 계정 등록 요청을 수신하여 비밀번호 해싱 및 DB 저장 수행
# 1) 입력 유효성 자동 검증: AuthRequest 스키마를 통해 필수 필드 누락 여부 1차 필터링
# 2) 세션 주입: 비동기 데이터베이스 커넥션 풀로부터 세션 획득
# 3) 서비스 위임: 비즈니스 유효성 검사, Bcrypt 해싱, DB 영속화는 auth.register()로 위임
# ==============================================================================
# 신규 회원 등록을 위한 HTTP POST 라우트 핸들러
@router.post("/register")
async def register_route(
    # 클라이언트가 전송한 회원가입 요청 DTO
    data : AuthRequest,
    # 의존성 주입을 통해 생성된 비동기 DB 세션
    db   : AsyncSession = Depends(get_db),
):
    # 비즈니스 계층의 register 서비스 함수로 회원가입 파이프라인 위임
    return await register(data, db)
