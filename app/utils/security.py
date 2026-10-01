import bcrypt
import jwt

from datetime import datetime, timedelta, timezone
from os       import getenv

# ==============================================================================
# [보안 설정 상수]
# JWT 서명에 사용할 대칭키(SECRET_KEY), 서명 알고리즘, 토큰 만료 시간 정의
# ==============================================================================
# 서버 환경변수에서 로드한 JWT 전자 서명용 비밀키 (대칭키)
KEY       = getenv("SECRET_KEY")
# 토큰 무결성 검증을 위한 HMAC-SHA256 대칭키 암호화 알고리즘
ALGORITHM = "HS256"
# 발급된 JWT 토큰의 유효 기간 (분 단위: 60분)
TOKEN_EXP = 60


# ==============================================================================
# [비밀번호 단방향 해싱: hash_password]
# 평문 비밀번호를 Bcrypt 적응형 단방향 해시 함수로 암호화
# 1) Salt(솔트) 자동 생성: 레인보우 테이블(Rainbow Table, 사전 계산된 해시표) 공격 무력화
# 2) Work Factor(Cost): GPU를 이용한 대규모 무차별 대입(Brute-Force) 공격을 지연시키기 위해
#    의도적으로 연산 라운드를 거쳐 해시 생성
# 3) 바이트 인코딩: Bcrypt는 바이트 스트림만 입력받으므로 UTF-8 encode() 후 최종 문자열로 decode()
# ==============================================================================
# 평문 비밀번호를 Bcrypt 해시 문자열로 변환하는 함수
def hash_password(
    # 사용자가 입력한 평문 비밀번호 문자열
    password: str,
):
    # 비밀번호에 고유 솔트를 부여하고 해싱한 후 데이터베이스 저장용 문자열로 디코딩
    return bcrypt.hashpw(
        # 문자열을 UTF-8 바이트 스트림으로 변환 (Bcrypt 필수 요구사항)
        password.encode("utf-8"),
        # 매 암호화마다 랜덤하게 생성되는 암호학적 솔트 (기본 Cost Factor 12 적용)
        bcrypt.gensalt(),
    ).decode("utf-8")


# ==============================================================================
# [비밀번호 일치 검증: verify_password]
# 사용자가 입력한 평문 비밀번호와 DB에 저장된 Bcrypt 해시의 일치 여부 확인
# 1) 해시 파싱: 저장된 해시 문자열에서 솔트와 Cost 라운드 정보를 자동으로 읽어 들임
# 2) 타이밍 공격(Timing Attack) 방어: bcrypt.checkpw는 비교 연산 시 글자별 시간차를
#    이용한 해킹을 막기 위해 상수 시간 비교(Constant-Time Comparison)를 수행함
# ==============================================================================
# 평문 비밀번호와 암호화된 해시 비밀번호의 일치 여부를 검증하는 함수
def verify_password(
    # 검증할 평문 비밀번호 문자열
    password: str,
    # DB에 저장되어 있던 기존 Bcrypt 해시 문자열 ($2b$... 형태)
    hashed_password: str,
):
    # 두 값을 바이트 스트림으로 변환하여 안전하게 상수 시간 일치 여부 검증
    return bcrypt.checkpw(
        # 검증 대상 평문 바이트
        password.encode("utf-8"),
        # 기준 해시 바이트
        hashed_password.encode("utf-8"),
    )


# ==============================================================================
# [JWT 토큰 발행기: create_token]
# 인증에 성공한 사용자 ID를 담은 서명된 JSON Web Token(JWT) 생성
# 1) 페이로드 클레임(Claims):
#    - 'id': 사용자 식별자 (Private Claim)
#    - 'exp': 만료 시각 (Standard Registered Claim, UTC 기준 현재 시각 + 60분)
# 2) 전자 서명: 서버만 알고 있는 SECRET_KEY와 HS256 알고리즘을 사용해 Header와 Payload를 서명
# 3) 클라이언트 반환: Base64URL로 인코딩된 Header.Payload.Signature 형태의 컴팩트 문자열 반환
# ==============================================================================
# 사용자 식별자를 포함한 서명된 JWT 액세스 토큰을 발급하는 함수
def create_token(
    # 토큰에 담길 사용자 식별자
    user_id: str,
):
    # UTC 기준 현재 시각에 유효 시간(60분)을 더한 토큰 만료 일시(exp) 계산
    exp = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_EXP)

    # JWT 페이로드에 저장될 클레임 딕셔너리 구성
    payload = {
        # 사용자 고유 식별자
        "id" : user_id,
        # 만료 일시 타임스탬프 (RFC 7519 표준 규격)
        "exp": exp
    }

    # 대칭키와 지정된 알고리즘으로 서명하여 최종 JWT 문자열 생성
    return jwt.encode(payload, KEY, algorithm=ALGORITHM)