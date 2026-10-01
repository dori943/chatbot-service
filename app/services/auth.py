from pymysql.constants      import ER
from sqlalchemy             import select
from sqlalchemy.exc         import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency  import run_in_threadpool

from app.core.errors        import APIError, ErrorCode
from app.core.logging       import log_event
from app.models.login       import Login
from app.schemas.auth       import AuthRequest
from app.utils.security     import verify_password, hash_password, create_token
from app.utils              import security


# ==============================================================================
# [유저 실존 검증기: check_user]
# JWT 토큰 인증 필터(get_token_id)에서 토큰 서명 통과 후 실제 DB 계정 존재 여부를 재확인
# 1) 쿼리 최적화: pw 등 불필요한 컬럼 조회를 배제하고 PK 인덱스만 타는 Login.id 단일 컬럼만 프로젝션
# 2) 상태 검증: 탈퇴한 유저나 강제 삭제된 유저의 유효한 토큰 재사용(Replay) 공격을 원천 차단
# 3) 트랜잭션 조기 종료: 조회 후 즉시 commit()을 호출하여 커넥션 풀에 점유 자원 즉시 반환
# ==============================================================================
# 데이터베이스에 해당 유저 아이디(user_id)가 실존하는지 여부를 반환하는 비동기 함수
async def check_user(user_id: str, db: AsyncSession) -> bool:
    try:
        # Login 테이블의 Primary Key(id)만 단일 컬럼으로 스칼라 조회 (인덱스 레인지 스캔 최적화)
        existing_id = await db.scalar(select(Login.id).where(Login.id == user_id))
        # 단순 읽기 쿼리 완료 후 즉시 커밋하여 트랜잭션 종료 및 커넥션 풀 반환
        await db.commit()
        # 식별자가 조회되었으면 True, 없으면 False 반환
        return existing_id is not None
    # 데이터베이스 통신 장애 또는 쿼리 오류 발생 시 예외 처리
    except SQLAlchemyError as exc:
        # 유저 조회 실패 이벤트 감사 로그 기록
        log_event("auth_user_lookup_failed", exc=exc)
        # 세션 롤백으로 미완료 트랜잭션 정리
        await db.rollback()
        # 호출자에게 데이터베이스 일시 장애(503) 전파
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "로그인 정보를 확인하지 못했습니다.") from None


# ==============================================================================
# [인증 입력 검증기: validate_auth]
# 회원가입 및 로그인 요청 데이터의 형식 정합성을 1차 비즈니스 레벨에서 검증
# 1) 아이디 공백 제거 및 필수 입력/최대 50자 제한 (DB 컬럼 VARCHAR(50) 초과 방지)
# 2) 비밀번호 필수 입력 검증
# 3) Bcrypt 72바이트 절삭 한계(Truncation Limit) 방어:
#    - Bcrypt 알고리즘은 내부 구조상 비밀번호를 최대 72바이트까지만 키로 사용함
#    - 72바이트를 초과하는 뒷부분은 조용히 잘려나가 무시되므로, 의도치 않은 해시 충돌 취약점 발생 가능
#    - 이를 방지하기 위해 UTF-8 바이트 기준으로 72바이트 초과 입력을 사전에 엄격히 차단(HTTP 422)
# 4) Fail-Fast (즉각 실패) 아키텍처:
#    - boolean 반환 대신 함수 내부에서 즉시 raise APIError(422)를 발생시킴
#    - 호출하는 쪽(register, login)에서 매번 if not validate_auth() 중복 코드를 작성할 필요 없이
#      호출부 코드를 단 1줄로 슬림화하고, 유효하지 않은 입력의 다음 로직 진행을 원천 차단
# ==============================================================================
# 회원가입 및 로그인 DTO 데이터(data)의 유효성을 검사하는 검증 함수
def validate_auth(data: AuthRequest):
    # 아이디 문자열의 앞뒤 공백 제거
    data.id = data.id.strip()
    # 아이디가 빈 문자열인 경우 유효성 예외 발생
    if not data.id:
        raise APIError(422, ErrorCode.INVALID_INPUT, "아이디를 입력해 주세요.")
    # 아이디가 DB 컬럼 최대 크기(VARCHAR 50)를 초과하는 경우 차단
    if len(data.id) > 50:
        raise APIError(422, ErrorCode.INVALID_INPUT, "아이디는 50자 이내로 입력해 주세요.")
    # 비밀번호의 앞뒤 공백을 제외한 실제 내용 존재 여부 검사
    if not data.pw.strip():
        raise APIError(422, ErrorCode.INVALID_INPUT, "비밀번호를 입력해 주세요.")
    # Bcrypt 알고리즘의 72바이트 입력 절삭 한계 초과 여부를 UTF-8 바이트 단위로 사전 차단
    if len(data.pw.encode("utf-8")) > 72:
        raise APIError(422, ErrorCode.INVALID_INPUT, "비밀번호는 UTF-8 기준 72바이트 이내로 입력해 주세요.")


# ==============================================================================
# [회원가입 파이프라인: register]
# 신규 사용자를 안전하게 암호화하여 데이터베이스에 영속화
# 1) 정합성 검증: validate_auth() 호출로 아이디/비밀번호 규격 검증
# 2) CPU 블로킹 방어 (run_in_threadpool):
#    - Bcrypt 해싱은 무차별 대입 공격을 막기 위해 의도적으로 연산 비용을 높인 CPU-bound 작업
#    - 단일 스레드 비동기 루프에서 직접 실행하면 전체 서버가 수백 ms 동안 멈추는 병목 유발
#    - Starlette의 run_in_threadpool로 OS 스레드풀에 작업을 위임하여 메인 이벤트 루프 무중단 보장
# 3) 중복 계정 예외 격리:
#    - DB INSERT 중 IntegrityError 발생 시 MySQL 네이티브 DUP_ENTRY(1062) 코드를 감별하여
#      이미 가입된 아이디인 경우 HTTP 409 Conflict (USER_EXISTS)로 정밀 변환
# ==============================================================================
# 신규 유저 계정을 생성하고 DB에 등록하는 비동기 함수
async def register(data: AuthRequest, db: AsyncSession):
    # 입력 데이터 유효성 검증
    validate_auth(data)
    # CPU 연산 집약적인 비밀번호 해싱을 별도 스레드풀로 오프로딩하여 이벤트 루프 블로킹 방지
    password = await run_in_threadpool(hash_password, data.pw)
    # 암호화된 비밀번호를 담은 Login 엔티티 인스턴스 생성
    user = Login(id=data.id, pw=password)

    try:
        # DB 세션 작업 목록에 엔티티 등록
        db.add(user)
        # 트랜잭션 커밋으로 DB 테이블에 영구 영속화
        await db.commit()
    # 데이터베이스 제약조건 위반 또는 일반 SQL 에러 발생 시 처리
    except SQLAlchemyError as exc:
        # 트랜잭션 롤백으로 미완료 작업 초기화
        await db.rollback()
        # MySQL 고유 에러 코드 1062 (ER.DUP_ENTRY) 중복 키 삽입 여부 정밀 판정
        if isinstance(exc, IntegrityError) and exc.orig.args and exc.orig.args[0] == ER.DUP_ENTRY:
            # 중복 아이디 충돌(HTTP 409) 예외 발생
            raise APIError(409, ErrorCode.USER_EXISTS, "이미 사용 중인 아이디입니다.") from None
        # 기타 데이터베이스 처리 실패 이벤트 로깅
        log_event("auth_register_failed", exc=exc)
        # DB 가용성 장애(HTTP 503) 예외 전파
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "회원가입을 완료하지 못했습니다.") from None

    # 회원가입 성공 감사 로그 기록
    log_event("auth_register_success")
    # 성공 안내 응답 딕셔너리 반환
    return {"message": "register success"}


# ==============================================================================
# [로그인 파이프라인: login]
# 유저 자격증명을 검증하고 세션 접근용 JWT 액세스 토큰을 발급
# 1) 필수 검증: validate_auth() 호출 및 서버 측 JWT 서명 키(SECRET_KEY) 주입 여부 확인
# 2) 고속 유저 엔티티 조회: SQLAlchemy의 PK 전용 최적화 메서드인 db.get() 사용
# 3) 왜 try 블록이 2개로 분리되어 있는가? (트랜잭션 격리 및 책임 분리):
#    - [1차 try: DB I/O 장애]: 실패 시 반드시 세션 롤백(await db.rollback())이 필요하며 503(DB_UNAVAILABLE) 처리
#    - [2차 try: 해시 포맷 파손]: Bcrypt C 라이브러리의 ValueError 처리로 롤백이 불필요하며 503(AUTH_UNAVAILABLE) 처리
#    - 둘을 하나의 try로 합치면 불필요한 DB 롤백이 돌거나 장애 원인이 혼탁해지므로 스코프를 최소화하여 분리
# 4) 단락 평가(Short-Circuit) vs 얼리 리턴(Early Return) 아키텍처:
#    - [현재 코드]: user is not None and await run_in_threadpool(...)
#      단락 평가로 유저 부재 시 해시 연산을 생략하고, 401 에러 발생 지점을 단 하나로 강제 일원화하여
#      개발자 실수로 인한 사용자 열거(User Enumeration) 보안 취약점 발생을 원천 차단
#    - [얼리 리턴 수용 방안]: 만약 팀 컨벤션이 가드 절(Guard Clause)을 중시한다면
#      'if user is None: raise 401'로 얼리 리턴하도록 유연하게 리팩토링 가능 (단, 동일한 401 메시지 유지 필수)
# 5) JWT 발급: 검증 통과 시 유효기간(60분)이 포함된 Bearer 토큰 생성 및 반환
# ==============================================================================
# 유저 자격증명을 확인하고 JWT 액세스 토큰을 반환하는 비동기 함수
async def login(data: AuthRequest, db: AsyncSession):
    # 입력 데이터 정합성 검증
    validate_auth(data)
    # 서버 환경변수에 JWT 서명용 비밀키(SECRET_KEY)가 설정되어 있는지 검증
    if not security.KEY:
        # 설정 누락 시 서비스 불가(HTTP 503) 예외 발생
        raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 서비스를 사용할 수 없습니다.")

    try:
        # Primary Key 기반의 최적화된 SQLAlchemy get() 메서드로 사용자 엔티티 조회
        user = await db.get(Login, data.id)
        # 조회 완료 후 즉시 커밋하여 트랜잭션 종료 및 커넥션 풀 반환
        await db.commit()
    # 유저 조회 쿼리 중 DB 장애 발생 시 처리
    except SQLAlchemyError as exc:
        # 로그인 조회 실패 로그 기록
        log_event("auth_login_lookup_failed", exc=exc)
        # 트랜잭션 롤백
        await db.rollback()
        # DB 가용성 장애(HTTP 503) 전파
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "로그인 정보를 확인하지 못했습니다.") from None

    try:
        # 1) user is not None: 사용자가 없으면 뒤의 해시 검증을 실행하지 않고 즉시 False (단락 평가)
        # 2) run_in_threadpool: CPU 집약적인 Bcrypt 패스워드 검증을 스레드풀로 오프로딩하여 이벤트 루프 보호
        valid = user is not None and await run_in_threadpool(verify_password, data.pw, user.pw)
    # DB에 저장된 패스워드 해시 문자열 형식이 깨져있거나 변조된 경우의 예외 처리
    except ValueError as exc:
        # 패스워드 검증 내부 오류 로깅
        log_event("auth_password_verify_failed", exc=exc)
        # 인증 서비스 오류(HTTP 503) 전파
        raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 정보를 확인하지 못했습니다.") from None
    # -------------------------------------------------------------------------
    # [왜 'if not valid' 검사는 try 블록 밖에 위치하는가? (예외 스코프 최소화)]
    #   1) try 스코프 최소화 원칙: try 안에는 실제 ValueError 예외를 유발할 수 있는 Bcrypt 연산만 한정 격리
    #   2) 시스템 결함(503)과 비즈니스 실패(401) 분리:
    #      - DB 해시 포맷 손상 등 서버 측 결함은 except ValueError에서 503(AUTH_UNAVAILABLE)으로 처리
    #      - 사용자의 단순 비밀번호 불일치는 정상적인 비즈니스 분기이므로 401(UNAUTHORIZED)로 처리
    #   3) 예외 마스킹(버그 은닉) 방지: 비즈니스 분기(if not valid)를 try 안에 넣으면 내부 오류 발생 시
    #      except에 가로채져 401 인증 실패가 엉뚱하게 503 서버 장애로 왜곡되는 버그 원천 예방
    # -------------------------------------------------------------------------
    # 유저가 존재하지 않거나 비밀번호가 일치하지 않는 경우
    if not valid:
        # 계정 존재 여부를 유출하지 않는 표준 401 미인증 예외 반환 (사용자 열거 공격 방어)
        raise APIError(401, ErrorCode.UNAUTHORIZED, "아이디 또는 비밀번호를 확인해 주세요.")

    # 사용자 고유 식별자를 페이로드에 담은 서명된 JWT 액세스 토큰 생성
    token = create_token(user.id)
    # 로그인 성공 감사 로그 기록
    log_event("auth_login_success")

    # 클라이언트가 로컬스토리지 등에 저장하여 Authorization 헤더에 실어 보낼 토큰 반환
    return {
        # 로그인 성공 안내 메시지
        "message"    : "login success",
        # 생성된 JWT 문자열
        "token"      : token,
        # HTTP Authorization 표준 인증 체계 규격 (Bearer)
        "token_type" : "bearer"
    }
