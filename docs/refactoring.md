# 리팩터링 변경 명세

| 항목 | 기준 |
|---|---|
| 기준일 | 2026-09-25 |
| 기능 비교 브랜치 | `develop` — `95396ac458581fdd085322126042eab126998b23` |
| 구조 기준 브랜치 | `feat/bsg-back/auth` — `c1befcda65995085f9d89cd00b5a036b95103049` |
| 변경 대상 | `refactor/bsg-back/app-refactoring` 작업 트리 |

## 1. 백엔드

### 1.1. 폴더별 책임과 변경 사항

| 위치 | 책임 | develop 대비 변경 |
|---|---|---|
| `app/routers/` | 경로, 요청 타입, 인증·DB 의존성 선언 및 서비스 호출 | 채팅 검증·AI 호출·저장·응답 구성 로직을 서비스로 이동 |
| `app/schemas/` | 요청 및 서비스 간 데이터 타입 선언 | 내용 검증을 서비스로 이동. HTTP 응답 모델 제거. `AIResult`를 서비스 간 전달 타입으로 분리 |
| `app/services/` | 입력 검증, 기능 실행, DB 조회·저장, 외부 AI 호출 | 인증·채팅 흐름·기록 처리·AI 연결 분리. 서비스 내부의 별도 DB 세션 생성 제거 |
| `app/core/` | 공통 설정, 인증 의존성, 오류 응답, 로그 출력 | AI 설정 이동, 사용자 확인을 인증 서비스로 위임, 예외 핸들러·로그 미들웨어 추가 |
| `app/models/` | 테이블·컬럼·관계의 ORM 매핑 | 기존 DDL에 맞게 `BIGINT`, `VARCHAR`, `DATETIME(6)` 타입 명시 |
| `app/utils/` | bcrypt 해시·검증, JWT 생성 | 연산 로직 유지. 서비스의 동기 bcrypt 호출에 스레드풀 적용 |
| `app/db.py` | 엔진·세션 팩토리·DB 의존성 | `AsyncSession`·`aiomysql` 적용 |
| `app/main.py` | 앱 구성 및 수명 주기 | 라우터·예외 핸들러·로그 미들웨어 등록. 앱 종료 시 DB 엔진 해제 |
| `data/` | DB 최초 초기화 | `init.sql` 변경 없음. 별도 스키마 마이그레이션 없음 |

### 1.2. 서비스 구성

| 모듈 | 주요 함수 | 책임 |
|---|---|---|
| `app/services/auth.py` | `register()`, `login()`, `check_user()` | 가입·로그인·사용자 존재 확인 |
| `app/services/chat_main.py` | `chat()`, `get_my_chat()` | 채팅 처리 순서, 내용 검증, HTTP 응답 데이터 구성 |
| `app/services/chat_db.py` | `save_result()`, `get_list_chat()`, `get_history()` | 대화 기록 저장·목록·문맥 조회 |
| `app/services/AI_connect.py` | `generate_answer()` | 문맥 구성, SDK 호출, 재시도·폴백, AI 오류 분류 |

채팅 요청의 처리 순서는 인증 → 질문 검증 → 문맥 조회 → AI 호출 → 결과 검증 → 기록 저장 → 응답 반환이다.
`AI_connect.py`는 DB 세션을 생성하거나 기록을 저장하지 않는다.

### 1.3. 인증 및 DB 세션 수명

`app/core/dependencies.py`의 `get_token_id()`는 Bearer 토큰의 서명·만료·ID를 검증하고
`app/services/auth.py`의 `check_user()`로 사용자 존재 여부를 조회한다.
인증 의존성과 라우터는 동일한 요청의 `get_db()` 의존성을 공유한다.
서비스와 기록 처리 함수는 전달받은 `AsyncSession`을 사용한다.

| 단계 | 세션·트랜잭션 동작 |
|---|---|
| 요청 시작 | `get_db()`에서 세션 생성 |
| 사용자·문맥·목록 조회 | 조회 완료 후 `commit()` |
| AI 대기 | 문맥 조회 트랜잭션 종료 상태. DB 연결 점유 없음 |
| 기록 저장 | `add()` 후 `commit()` |
| DB 예외 | 해당 서비스에서 `rollback()` |
| 요청 종료 | `get_db()` 컨텍스트 종료 시 세션 닫기 |
| 앱 종료 | lifespan에서 `engine.dispose()` |

사용자 확인은 ID, 문맥 조회는 질문·답변, 목록 조회는 응답에 필요한 다섯 컬럼만 선택한다.
문맥은 본인의 성공 기록을 ID 내림차순으로 제한 조회한 뒤 시간순으로 AI에 전달한다.
목록은 `created_at DESC, id DESC`로 반환한다.

### 1.4. 검증 및 실패 처리

필수 필드·자료형·JSON 구문 검증은 FastAPI/Pydantic이 수행한다.
공백·길이·AI 결과 유효성 검증은 서비스에 위치한다. 정의되지 않은 JSON 필드는 무시한다.
인증된 사용자 ID는 토큰에서 취득한다.

| 검증 대상 | 조건 | 실패 결과 |
|---|---|---|
| 인증 입력 | ID·비밀번호의 공백 입력 거부, ID 최대 50자, 비밀번호 UTF-8 최대 72바이트 | 422 `INVALID_INPUT` |
| 질문 | 앞뒤 공백 제거 후 빈 값 거부, 최대 `min(MAX_QUESTION_LENGTH, 5000)`자 | 422 `INVALID_INPUT` |
| AI 성공 답변 | 공백이 아닌 문자열, 최대 5,000자 | 실패 기록 저장 후 502 |
| 중복 가입 | MySQL 중복 키 오류 | 409 `USER_ALREADY_EXISTS` |
| 로그인·토큰 | 계정 정보 불일치, 토큰 누락·만료·위조, 사용자 없음 | 401 `UNAUTHORIZED` |
| 인증 설정·저장된 비밀번호 해시 | 서명 키 누락 또는 해시 검증 오류 | 503 `AUTH_UNAVAILABLE` |

| 실패 지점 | 후속 처리 |
|---|---|
| 인증·입력 검증 | AI 호출 및 채팅 기록 저장 없이 오류 반환 |
| 문맥 조회 | 롤백 후 빈 문맥으로 AI 호출 |
| AI 호출·결과 검증 | `answer=null`인 실패 기록 저장 후 오류 반환 |
| 기록 저장·목록 조회 | 롤백 후 503 `DB_UNAVAILABLE` 반환 |
| 처리되지 않은 내부 예외 | 공통 핸들러에서 500 `INTERNAL_ERROR` 반환 |

### 1.5. HTTP 인터페이스 변경

| 항목 | develop 대비 현재 계약 |
|---|---|
| 가입·로그인 성공 | 성공 메시지 유지. 로그인 응답의 `token`, `token_type` 유지 |
| 로그인 실패 | HTTP 200 대신 401 반환 |
| 채팅 성공 | HTTP 200. `answer`, `request_id`, `created_at` 유지. 시각은 UTC `Z` 문자열 |
| 본인 기록 조회 | `{items, total}` 대신 전체 배열 반환. 페이지네이션 없음 |
| 기록 항목 | `id`, `question`, `answer`, `status`, `created_at` |
| 서비스·검증 오류 | `error_code`, `message`, `request_id`로 통일 |
| 기본 HTTP 오류 | 404·405 등 프레임워크 응답의 `detail` 형식 유지 |
| 요청 식별 | `X-Request-ID` 헤더 추가. 오류 응답·로그·채팅 기록에 동일 ID 사용 |

AI 오류의 HTTP 상태는 시간 초과 504, 호출 제한 429, 안전 필터 차단 422, 나머지 AI 오류 502이다.
서비스는 dict·list를 반환하거나 `APIError`를 발생시키며, `app/core/errors.py`의 예외 핸들러가 오류 응답을 구성한다.
`ChatResponse`, `ChatLogItem`, `ErrorResponse`는 사용하지 않는다.

### 1.6. 로그

로그 레벨·메시지 형식·출력은 `app/core/logging.py`에서 관리한다.
호출부는 `log_event()`에 이벤트와 값을 전달하며, 요청 ID는 `ContextVar`로 분리한다.

| 요청 이벤트 | 기록 시점·항목 |
|---|---|
| `request_received` | 앱 처리 전. 요청 ID와 HTTP 메서드 |
| `request_completed` | 정상 완료 또는 예외 종료. 요청 ID, 메서드, 라우트, 상태, 처리 시간 |
| `request_cancelled` | 요청 작업 취소. 요청 ID, 메서드, 라우트, 처리 시간 |

수신 단계는 라우트 매칭 전이므로 원본 경로·쿼리·본문을 기록하지 않는다.
취소는 호출자에게 전파하며 HTTP 500 완료 로그와 구분한다.

로그 항목은 요청 결과, 처리 시간, AI 모델·시도 횟수, 예외 종류·발생 위치이다.
질문·답변 본문, 비밀번호, 토큰, 예외 원문은 앱 이벤트 로그에서 제외한다.
Uvicorn의 예외 로그는 필터에서 예외 종류와 발생 위치로 변환한다.

## 2. 프론트엔드

| 위치 | develop 대비 변경 |
|---|---|
| `static/js/auth.js` | 인증 실패 응답의 `message`가 문자열이면 화면에 표시. 그 외에는 기본 오류 문구 표시 |
| `templates/`, 나머지 채팅 JS | 변경 없음 |

대화방 생성·삭제와 화면 기록은 `localStorage`를 사용한다.
화면은 `/api/me/chats`를 호출하지 않으며 서버에는 대화방 CRUD API가 없다.
AI 문맥은 사용자별 기록 기준이므로 화면의 새 대화방 생성과 독립적이다.

## 3. AI

### 3.1. 모듈 분리

| develop의 위치·책임 | 현재 위치 |
|---|---|
| `app/services/ai_service.py`: AI 연결·문맥·재시도·폴백 | `app/services/AI_connect.py` |
| `app/services/ai_service.py`: AI 설정 | `app/core/config.py` |
| `app/services/ai_service.py`: AI 결과 타입 | `app/schemas/chat.py`의 `AIResult` |
| `app/services/ai_service.py`: 질문 검증 | `app/services/chat_main.py` |
| `app/services/prompt.py`: 시스템 프롬프트 | 동일 파일, 내용 변경 없음 |

### 3.2. 호출 계약 및 처리 정책

호출 인터페이스는 `generate_answer(question, history=None, *, user_id=None, request_id=None) -> AIResult`이다.
입력 검증·DB 저장·HTTP 오류 변환은 호출 서비스의 책임이며 AI 호출 결과는 `AIResult`로 전달한다.

문맥 선택, 재시도 대상, 폴백 판단, 결과 모델명 처리, 클라이언트 캐시는 develop의 동작을 유지한다.
AI 처리 로그는 `app/core/logging.py`의 `log_event()`를 사용한다.

| 제한 | 적용 위치 |
|---|---|
| `AI_TIMEOUT_SECONDS` | AI 모델별 호출 제한 시간 산정 |
| `AI_TOTAL_TIMEOUT_SECONDS` | AI 내부 잔여 시간 산정 및 `chat_main.py`의 전체 AI 대기 제한 |
| `AI_CONTEXT_TURNS`, `MAX_CONTEXT_CHARS` | 최근 문맥 선택 및 오래된 대화 제외 |

## 4. 테스트 구성

| 위치 | 구성 |
|---|---|
| `tests/` | 전용 MySQL 기반 API·DB 테스트, 모킹 기반 AI·로그·비동기 테스트, 선택 실행 브라우저·실제 AI 테스트 |
| `docker-compose.test.yml` | 개발 환경과 분리된 MySQL 테스트 컨테이너 |
| `scripts/ai_smoke_test.py` | 독립 실행형 AI 검증. `basic`, `context`, `timeout`, `validation`, `limit`, `fallback` 인자 |
| `scripts/check_logs.sql` | 대화 기록 조회·집계 쿼리 |

실행 환경·명령·판정 조건: [테스트 가이드](testing-guide.md).
API 경로·요청·응답 형식: [README](../README.md).
