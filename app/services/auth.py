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
# 1) 필요한 값만 조회: pw 등 불필요한 컬럼을 가져오지 않고 Login.id만 선택해 PK 조건으로 조회
# 2) 존재 검증: 삭제되어 현재 DB에 없는 계정의 토큰을 거절. 계정 정지나 모든 토큰 재사용을 막는 기능은 아님
# 3) 트랜잭션 조기 종료: 조회 후 즉시 commit()을 호출하여 커넥션 풀에 점유 자원 즉시 반환
# ==============================================================================
# 데이터베이스에 해당 유저 아이디(user_id)가 실존하는지 여부를 반환하는 비동기 함수
async def check_user(user_id: str, db: AsyncSession) -> bool:
    try:
        # [스칼라(Scalar) 조회: db.scalar]
        # - 2차원 표(행/열 튜플) 포장지를 뜯고 단 하나의 순수한 단일 값(스칼라 값)만 즉시 추출
        # - Login.id만 조회하고 PK 동등 조건으로 사용자를 찾음. 실제 실행 계획·속도는 DB에서 확인해야 함
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
        # [예외 전파: raise (vs assert)]
        # - C#/C++(Unity/Unreal)의 'throw'와 동일하게 비상 상황에서 함수의 정상 흐름을 즉시 중단하고 예외 송출
        # - 개발자 내부 디버깅용인 assert(최적화 배포 시 -O 옵션으로 증발)와 달리,
        #   raise는 프로덕션 런타임 환경에서도 항상 살아남아 비즈니스 예외와 시스템 장애를 안전하게 통제함
        # - 호출자에게 데이터베이스 일시 장애(503) 전파
        raise APIError(503, ErrorCode.DB_UNAVAILABLE, "로그인 정보를 확인하지 못했습니다.") from None


# ==============================================================================
# [인증 입력 검증기: validate_auth]
# 회원가입 및 로그인 요청 데이터의 형식 정합성을 1차 비즈니스 레벨에서 검증
# 1) 아이디 공백 제거 후 3~50자 검사 (DB 컬럼 VARCHAR(50)과 서비스 최소 길이 규칙)
# 2) 비밀번호는 공백만 있는 입력을 거절하고 8자 이상인지 검사. 실제 비밀번호의 앞뒤 공백은 보존
# 3) Bcrypt 입력의 72바이트 경계:
#    - 문자 수와 UTF-8 바이트 수는 다름. 한글·이모지를 포함하면 8자도 8바이트보다 길어질 수 있음
#    - 라이브러리에 초과 입력을 넘긴 뒤의 동작에 의존하지 않고 서비스에서 먼저 422로 거절
#    - auth-ui.submitAuth도 같은 길이 규칙을 확인하지만 직접 API 호출을 대비해 서버 검사가 반드시 필요
# 4) Fail-Fast (즉각 실패) 아키텍처:
#    - boolean 반환 대신 함수 내부에서 즉시 raise APIError(422)를 발생시킴
#    - 호출하는 쪽(register, login)에서 매번 if not validate_auth() 중복 코드를 작성할 필요 없이
#      호출부 코드를 단 1줄로 슬림화하고, 유효하지 않은 입력의 다음 로직 진행을 원천 차단
# ==============================================================================
# 회원가입 및 로그인 DTO 데이터(data)의 유효성을 검사하는 검증 함수
# 성공하면 명시적 반환값 없이 끝나고, 실패하면 raise로 호출자의 다음 단계를 중단한다.
# data.id를 직접 정규화하므로 호출한 register/login은 같은 객체의 정리된 ID를 사용한다.
def validate_auth(data: AuthRequest):
    # 아이디 문자열의 앞뒤 공백 제거
    data.id = data.id.strip()
    if not 3 <= len(data.id) <= 50:       raise APIError(422, ErrorCode.INVALID_INPUT, "아이디는 3~50자로 입력해 주세요.")
    if not data.pw.strip():               raise APIError(422, ErrorCode.INVALID_INPUT, "비밀번호를 입력해 주세요.")
    if len(data.pw) < 8:                  raise APIError(422, ErrorCode.INVALID_INPUT, "비밀번호는 8자 이상으로 입력해 주세요.")
    if len(data.pw.encode("utf-8")) > 72: raise APIError(422, ErrorCode.INVALID_INPUT, "비밀번호는 UTF-8 기준 72바이트 이내로 입력해 주세요.")


# ==============================================================================
# [회원가입 파이프라인: register]
# 비밀번호를 해시로 저장하고 신규 사용자에게 JWT를 발급하는 흐름
# 1) 정합성 검증: validate_auth() 호출로 아이디/비밀번호 규격 검증
# 2) CPU 블로킹 방어 (run_in_threadpool):
#    - Bcrypt 해싱은 무차별 대입 공격을 막기 위해 의도적으로 연산 비용을 높인 CPU-bound 작업
#    - 이벤트 루프에서 직접 실행하면 같은 루프의 다른 요청 처리가 그 연산 동안 지연될 수 있음
#    - run_in_threadpool로 연산을 위임하고 await로 결과를 기다림. 연산 비용이나 자원 한계가 없어지는 것은 아님
# 3) 중복 계정 예외 격리:
#    - DB INSERT 중 IntegrityError 발생 시 MySQL 네이티브 DUP_ENTRY(1062) 코드를 감별하여
#      이미 가입된 아이디인 경우 HTTP 409 Conflict (USER_EXISTS)로 정밀 변환
# 4) 현재 회원가입은 토큰도 반환: auth-ui가 토큰을 저장하므로 별도 로그인 없이 가입 직후 로그인 상태로 전환
# ==============================================================================
# 신규 유저 계정을 생성하고 DB에 등록하는 비동기 함수
async def register(data: AuthRequest, db: AsyncSession):
    # 입력 데이터 유효성 검증
    validate_auth(data)
    # 가입 성공에도 create_token을 호출하므로 DB에 계정을 만들기 전에 서명 키가 있는지 확인한다.
    if not security.KEY: raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 서비스를 사용할 수 없습니다.")

    # 함수 자체와 인자를 전달한다. hash_password(data.pw)를 먼저 계산해서 넘기는 형태가 아니다.
    password = await run_in_threadpool(hash_password, data.pw)
    # 비밀번호 원문 대신 해시를 담은 Login 엔티티 인스턴스 생성
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

    # DB 저장이 완료된 계정에 토큰 발급. 브라우저 저장소에 넣는 일은 auth-ui.js가 수행한다.
    token = create_token(user.id)
    log_event("auth_register_success")

    # 가입과 로그인 응답의 공통 계약: message, token, token_type.
    return {
        "message"    : "register success",
        "token"      : token,
        "token_type" : "bearer"
    }


# ==============================================================================
# [로그인 파이프라인: login]
# 유저 자격증명을 검증하고 세션 접근용 JWT 액세스 토큰을 발급
# 1) 필수 검증: validate_auth() 호출 및 서버 측 JWT 서명 키(SECRET_KEY) 주입 여부 확인
# 2) 고속 유저 엔티티 조회: SQLAlchemy의 PK 전용 최적화 메서드인 db.get() 사용
# 3) 왜 try 블록이 2개로 분리되어 있는가? (트랜잭션 격리 및 책임 분리):
#    - [1차 try: DB I/O 장애]: 실패 시 반드시 세션 롤백(await db.rollback())이 필요하며 503(DB_UNAVAILABLE) 처리
#    - [2차 try: 해시 검증 오류]: bcrypt의 ValueError는 이미 조회 트랜잭션을 종료한 뒤 발생하며 503(AUTH_UNAVAILABLE) 처리
#    - 둘을 하나의 try로 합치면 불필요한 DB 롤백이 돌거나 장애 원인이 혼탁해지므로 스코프를 최소화하여 분리
# 4) 단락 평가(Short-Circuit) vs 얼리 리턴(Early Return) 아키텍처:
#    - [현재 코드]: user is not None and await run_in_threadpool(...)
#      단락 평가로 유저 부재 시 해시 연산을 생략하고, 401 에러 발생 지점을 단 하나로 강제 일원화하여
#      아이디 부재와 비밀번호 불일치의 응답 문구를 일치시킴. 연산 생략에 따른 시간 차이까지 없애지는 않음
#    - [얼리 리턴 수용 방안]: 만약 팀 컨벤션이 가드 절(Guard Clause)을 중시한다면
#      'if user is None: raise 401'로 얼리 리턴하도록 유연하게 리팩토링 가능 (단, 동일한 401 메시지 유지 필수)
# 5) Bcrypt vs JWT의 역할 분담과 협업 메커니즘 (본인 확인 vs 출입 통행증):
#    - [Bcrypt: 인증(Authentication) 단계]:
#      로그인 요청 시점에 DB의 비밀번호 해시와 사용자의 입력 패스워드를 대조하는 본인 확인 절차
#    - [JWT: 후속 요청의 인증 정보]:
#      Bcrypt 본인 확인 통과 후, 사용자가 매번 비밀번호를 재입력하지 않도록 유저 ID와 만료시간(60분)을 담아
#      서명된 토큰을 응답으로 반환. 브라우저가 localStorage에 저장하고 후속 채팅 요청에 첨부
#      서버는 토큰으로 사용자를 인증한 뒤, 그 사용자 ID로 조회 범위를 제한하여 본인 기록만 접근하도록 제어
# ==============================================================================
# 유저 자격증명을 확인하고 JWT 액세스 토큰을 반환하는 비동기 함수
async def login(data: AuthRequest, db: AsyncSession):
    # 입력 데이터 정합성 검증
    validate_auth(data)
    if not security.KEY: raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 서비스를 사용할 수 없습니다.")

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
        # [단락 평가(Short-Circuit)와 CPU 오프로딩의 결합 구조]
        # 1) 단락 평가 (user is not None and ...):
        #    - A and B에서 앞선 조건(user is not None)이 False(유저 부재)이면,
#        #      Python은 뒤의 await 호출을 평가하지 않고 False로 판정 (임의의 실행 시간 수치를 보장하지 않음)
        #    - user.pw에 접근하지 않아 None 속성 오류를 피하고, 없는 계정의 해시 대조를 생략
        # 2) run_in_threadpool (CPU 블로킹 방어 / 스레드풀 외주):
        #    - Bcrypt는 의도적으로 연산 비용을 둔 동기 작업이므로 이벤트 루프에서 직접 실행하면 다른 요청이 지연될 수 있음
        #    - run_in_threadpool에 verify_password 함수와 인자를 맡기고 await로 결과를 기다림
        #    - await가 CPU 연산 자체를 없애거나 호출을 자동으로 병렬화하는 것은 아님
        # 3) valid 판정:
        #    - 유저 실존 + 비밀번호 일치 ➔ True (로그인 승인 진행)
        #    - 유저 부재 or 비밀번호 불일치 ➔ False (401 비상벨 raise 트리거)
        valid = user is not None and await run_in_threadpool(verify_password, data.pw, user.pw)
    # DB에 저장된 패스워드 해시 문자열 형식이 깨져있거나 변조된 경우의 예외 처리
    except ValueError as exc:
        # 패스워드 검증 내부 오류 로깅
        log_event("auth_password_verify_failed", exc=exc)
        # 인증 서비스 오류(HTTP 503) 전파
        raise APIError(503, ErrorCode.AUTH_UNAVAILABLE, "인증 정보를 확인하지 못했습니다.") from None
    if not valid: raise APIError(401, ErrorCode.UNAUTHORIZED, "아이디 또는 비밀번호를 확인해 주세요.")

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
