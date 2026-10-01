from os                     import getenv

from sqlalchemy.engine      import URL
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm         import declarative_base

# ==============================================================================
# [비동기 데이터베이스 접속 URL 구성]
# 비동기 MySQL 드라이버(mysql+aiomysql)를 사용한 연결 설정
# 1) 드라이버: aiomysql을 적용하여 DB 쿼리 실행 시 파이썬 이벤트 루프 블로킹 방지
# 2) 문자셋: 이모지 및 다양한 언어 처리를 위해 4바이트 유니코드인 utf8mb4 명시
# ==============================================================================
# 환경변수로부터 데이터베이스 접속 정보를 읽어와 안전한 URL 객체 생성
DATABASE_URL = URL.create(
    # 비동기 지원 MySQL 드라이버 규격
    drivername = "mysql+aiomysql",
    # DB 사용자 계정명
    username   = getenv("MYSQL_USER"),
    # DB 비밀번호
    password   = getenv("MYSQL_PASSWORD"),
    # DB 호스트명 (Docker Compose 네트워크 상의 컨테이너 이름: 'db')
    host       = "db",
    # MySQL 기본 포트
    port       = 3306,
    # 접속 대상 데이터베이스 스키마명
    database   = getenv("MYSQL_DATABASE"),
    # 4바이트 이모지 지원 문자셋 쿼리 파라미터
    query      = {"charset": "utf8mb4"},
)

# ==============================================================================
# [비동기 DB 엔진 및 커넥션 풀 생성: create_async_engine]
# pool_pre_ping=True (비관적 연결 끊김 감지):
# - MySQL의 wait_timeout 등으로 인해 유휴(Idle) 상태의 커넥션이 서버 측에서 끊어졌을 때,
# - 풀에서 커넥션을 꺼내는 시점에 가벼운 'SELECT 1' 핑(Ping)을 날려 유효성을 사전 확인
# - 죽은 커넥션이면 자동으로 폐기하고 신규 커넥션을 수립하여 'MySQL server has gone away' 장애 원천 예방
# ==============================================================================
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
# SQLAlchemy ORM 모델 클래스들이 상속받을 공통 선언적 베이스 클래스
Base   = declarative_base()

# ==============================================================================
# [비동기 세션 팩토리: SessionLocal]
# 1) autoflush=False: 쿼리 실행 전 암묵적 flush를 방지하고 명시적 제어 유지
# 2) expire_on_commit=False (비동기 환경 필수 최적화):
#    - SQLAlchemy 기본값은 commit() 후 객체 속성을 만료시켜, 재접근 시 Lazy Loading SELECT를 발생시킴
#    - 비동기 환경에서는 동기 속성 접근 시 I/O를 수행할 수 없어 MissingGreenlet 에러가 발생하므로,
#      커밋 후에도 메모리 객체 속성을 그대로 유지하도록 False 지정
# ==============================================================================
SessionLocal = async_sessionmaker(
    autoflush        = False,
    expire_on_commit = False,
    bind             = engine,
)

# ==============================================================================
# [세션 생명주기 관리자: get_db]
# FastAPI 의존성 주입(Depends(get_db))을 위한 비동기 제너레이터 함수
# 1) 요청 진입 시 비동기 세션을 생성하여 핸들러에 공급(yield)
# 2) 핸들러 실행 종료 및 응답 반환 후 컨텍스트 매니저에 의해 세션 자동 종료(close)
# 3) 사용이 끝난 물리 커넥션은 소멸되지 않고 커넥션 풀로 안전하게 반환(Return to Pool)
# ==============================================================================
async def get_db():
    # SessionLocal 비동기 컨텍스트 매니저 진입
    async with SessionLocal() as db:
        # 호출자에게 활성화된 세션 인스턴스 양도
        yield db
