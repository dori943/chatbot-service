import jwt

from fastapi                import Depends
from fastapi.security       import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors        import APIError, ErrorCode
from app.db                 import get_db
from app.services           import auth
from app.utils              import security

# ==============================================================================
# [HTTP Bearer 인증 스키마 설정]
# 요청 헤더의 'Authorization: Bearer <토큰>' 규격을 파싱하기 위한 FastAPI 보안 스키마 객체
# auto_error=False로 설정하여 헤더 누락 시 FastAPI 기본 403 에러 대신 애플리케이션 표준
# APIError(401, UNAUTHORIZED) 응답을 일관되게 반환하도록 제어
# ==============================================================================
bearer = HTTPBearer(auto_error=False)


# ==============================================================================
# [JWT 토큰 검증 및 유저 식별자 추출 의존성: get_token_id]
# 인증이 필요한 API 엔드포인트(예: POST /chat, GET /me/chats)에서 Depends()로 주입받아 사용
#
# [5단계 엄격한 보안 검증 파이프라인]
# 1) 헤더 유무 검사: Authorization 헤더 및 Bearer 토큰 존재 여부 확인
# 2) 서버 키 검사: JWT 서명 검증용 서버 비밀키(SECRET_KEY) 주입 상태 확인
# 3) 암호학적 서명 및 만료 검증: jwt.decode()를 통해 위변조 방지 및 만료(exp) 자동 확인
# 4) 클레임 무결성 검증: 'id' 클레임의 타입(str), 비어있지 않음, 최대 길이(50자) 검증
# 5) 실시간 DB 계정 실존 검증 (Stateful DB Check):
#    - 무상태(Stateless) JWT의 치명적 약점: 토큰 발급 후 계정이 탈퇴/정지되어도 만료 전까지 유효함
#    - 이를 해결하기 위해 auth.check_user()로 DB에 실제 계정이 존재하는지 즉각 재확인하여
#      탈퇴 유저의 잔여 토큰 재사용(Replay) 공격을 원천 차단
# ==============================================================================
# HTTP 요청으로부터 토큰을 추출·검증하여 유효한 사용자 ID 문자열을 반환하는 비동기 의존성 함수
async def get_token_id(
    # HTTP 헤더로부터 추출된 Bearer 자격증명 객체 (토큰 누락 시 None)
    credentials : HTTPAuthorizationCredentials | None = Depends(bearer),
    # 데이터베이스 상태 조회를 위한 비동기 DB 세션 의존성
    db          : AsyncSession                        = Depends(get_db),
) -> str:
    # 인증 실패 시 클라이언트에 일관되게 반환할 401 표준 에러 객체 사전 생성
    failed = APIError(401, ErrorCode.UNAUTHORIZED, "로그인이 필요합니다. 다시 로그인해 주세요.")
    # Authorization 헤더가 누락되었거나 Bearer 형식이 아닌 경우 차단
    if credentials is None:
        raise failed
    # 서버 환경변수에 서명 검증용 비밀키가 주입되지 않은 경우 서비스 불가(HTTP 503) 전파
    if not security.KEY:
        raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 서비스를 사용할 수 없습니다.")

    try:
        # JWT 토큰의 서명(Signature) 유효성, 만료 시각(exp), 필수 클레임 존재 여부를 복합 검증 및 디코딩
        claims = jwt.decode(
            # HTTP 헤더에서 추출한 순수 토큰 문자열
            credentials.credentials,
            # 서버 비밀키
            security.KEY,
            # 허용할 전자 서명 알고리즘 화이트리스트 (HS256)
            algorithms = [security.ALGORITHM],
            # 페이로드 내에 id와 exp 클레임이 반드시 포함되어야 함을 강제
            options    = {"require": ["id", "exp"]},
        )
    # 토큰 위변조, 서명 불일치, 만료, 포맷 파손 등 모든 JWT 디코딩 예외 처리
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError):
        # 내부 예외 트레이스백을 은닉하고 표준 401 예외 반환
        raise failed from None

    # 디코딩된 페이로드에서 사용자 식별자 추출
    user_id = claims["id"]
    # 사용자 식별자가 문자열이 아니거나 빈 값이거나 최대 허용 길이(50자)를 초과한 경우 차단
    if not isinstance(user_id, str) or not user_id or len(user_id) > 50:
        raise failed

    # 데이터베이스를 실시간 조회하여 해당 유저가 실제로 존재하는지 검증 (탈퇴/정지 유저 즉각 차단)
    if not await auth.check_user(user_id, db):
        raise failed

    # 모든 검증을 완벽히 통과한 검증된 사용자 식별자 반환 (라우터 핸들러의 user_id 인자로 주입됨)
    return user_id
