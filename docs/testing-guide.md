# 테스트 가이드

| 항목 | 내용 |
|---|---|
| 최초 작성자·작성일 | 이건탁 · 2026-09-22 |
| 최종 수정일 | 2026-09-25 |
| 대상 브랜치 | `refactor/bsg-back/app-refactoring` |
| 실행 검증 | 2026-09-25: MySQL·Chromium pytest 114 passed, 1 deselected / JS 11 passed / 오프라인 AI 스모크 3개 시나리오 통과 |

실행 검증은 모의 AI 응답을 사용했다. 실제 AI 호출 테스트 1개와 외부 배포 환경은 검증 대상에서 제외했다.
pytest 실행 시 의존 라이브러리의 사용 중단 예정 경고 3건이 발생했으며, 테스트 실패는 없었다.

## 환경 요구사항

| 구성 요소 | 사용 범위 |
|---|---|
| Python·pip | 백엔드·pytest·AI 스모크 실행. 앱 Docker 이미지 기준 Python 3.12 |
| `requirements-dev.txt` | 앱 의존성과 pytest·httpx·Playwright·python-dotenv |
| Docker Desktop | 전용 MySQL 8.0 및 앱 Compose 실행 |
| Playwright Chromium | 브라우저 통합 테스트 |
| Node.js | `tests/chat-api.test.mjs` |

명령 실행 위치는 저장소 루트이며, 셸은 Windows PowerShell 기준이다.
가상환경 실행 파일을 직접 사용한다. macOS/Linux의 Python 경로는 `.venv/bin/python`이다.

```powershell
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 환경변수와 실행 조건

| 변수 | 조건·용도 |
|---|---|
| `MYSQL_TEST_URL` | DB 테스트에 필수. MySQL의 `chatbot_integration_test` 데이터베이스만 허용 |
| `RUN_BROWSER_TESTS` | 정확히 `1`일 때 브라우저 테스트 실행 |
| `RUN_LIVE_AI` | 정확히 `1`이고 테스트에 `live_ai` 표시가 있을 때 실제 AI 호출 허용 |
| `BROWSER_CHANNEL` | 브라우저 채널 지정. 미설정 시 Playwright Chromium 사용 |
| `AI_API_KEY` | 실제 AI pytest와 스모크의 실제 호출 사례에 필수 |
| `AI_MODEL`, `AI_FALLBACK_MODEL` | 실제 AI 호출의 주 모델·대체 모델 설정 |

일반 pytest는 `.env`를 자동으로 읽지 않는다. 기본 테스트의 인증 키와 계정은
`tests/conftest.py`에서 설정하므로 실제 `.env`와 API 키가 필요하지 않다.
실제 AI pytest의 `.env` 로딩은 별도 실행 명령에 포함된다. AI 스모크는 `.env`를 직접 읽는다.

## 전용 MySQL

| 항목 | 값 |
|---|---|
| Compose 파일 | `docker-compose.test.yml` |
| 프로젝트·서비스 | `chatbot-validation-test` · `db-test` |
| 접속 주소 | `127.0.0.1:13307` |
| 데이터베이스 | `chatbot_integration_test` |
| 저장 방식 | `tmpfs`, 컨테이너 종료 시 데이터 소멸 |

fixture는 **매 테스트 전후 `login`, `chat_logs` 데이터를 삭제**하고 테스트 계정을 준비한다.
개발 DB를 테스트 대상으로 사용하지 않는다. **같은 테스트 DB를 사용하는 pytest의 동시·병렬 실행은 금지한다.**
앱의 DB 접근은 `AsyncSession + aiomysql`, fixture의 준비·결과 조회는 동기 드라이버를 사용한다.

```powershell
docker compose -p chatbot-validation-test -f docker-compose.test.yml up -d --wait db-test

$env:MYSQL_TEST_URL='mysql+pymysql://root:integration-test-only@127.0.0.1:13307/chatbot_integration_test?charset=utf8mb4'
```

## 검증 명령

### 기본 전체 테스트

전용 MySQL과 Chromium 설치가 실행 조건이다. 실제 AI 테스트는 선택 대상에서 제외한다.

```powershell
$env:RUN_BROWSER_TESTS='1'
$env:RUN_LIVE_AI='0'

.\.venv\Scripts\python.exe -B -m pytest tests -m 'not live_ai' -q -p no:cacheprovider
node --test tests/chat-api.test.mjs
```

### AI 단위 테스트

DB·브라우저·실제 API 키 없이 실행한다. 외부 AI 호출은 테스트에서 대체한다.

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_ai_connect.py -q -p no:cacheprovider
```

### 브라우저 테스트

전용 MySQL과 `MYSQL_TEST_URL`이 필요하다. 테스트는 임의의 로컬 포트에서 Uvicorn을 실행하고
Chromium → 화면 → API → 테스트 DB 흐름을 검증한다. AI 응답은 모킹한다.

```powershell
$env:RUN_BROWSER_TESTS='1'
.\.venv\Scripts\python.exe -B -m pytest tests/test_browser_integration.py -q -p no:cacheprovider
```

`RUN_BROWSER_TESTS='0'`은 기본 전체 실행에서 브라우저 테스트만 제외한다.

### 실제 AI pytest

전용 MySQL·`MYSQL_TEST_URL`·유효한 AI 키가 필요하다. 실제 AI 호출에는 사용량이 발생한다.
`dotenv run`으로 `.env`를 읽은 뒤 테스트를 실행한다.

```powershell
$env:RUN_LIVE_AI='1'
try {
    .\.venv\Scripts\python.exe -B -m dotenv run -- .\.venv\Scripts\python.exe -B -m pytest tests/test_live_ai.py -q -p no:cacheprovider
} finally {
    $env:RUN_LIVE_AI='0'
}
```

### AI 스모크 스크립트

`scripts/ai_smoke_test.py`는 서버·DB 없이 실행되는 독립 스크립트다.

| 인자 | 검증 내용 | 실제 AI 호출 |
|---|---|---|
| `basic` | 기본 질문에 대한 성공 응답 | 있음 |
| `context` | 이전 질문의 문맥 반영 | 있음 |
| `timeout` | 짧은 호출 제한 시간의 타임아웃 결과 | 있음 |
| `validation` | 빈 값·타입·길이 오류 거부 | 없음 |
| `limit` | 문맥 길이·턴 수 출력, 답변 없는 대화 제외 | 없음 |
| `fallback` | 가짜 실패에 따른 대체 모델 호출·오류 처리 | 없음 |

```powershell
# 외부 AI 호출 없음
.\.venv\Scripts\python.exe -B scripts/ai_smoke_test.py validation limit fallback

# 외부 AI 호출 있음
.\.venv\Scripts\python.exe -B scripts/ai_smoke_test.py basic context
```

인자 생략 시 여섯 사례를 모두 선택한다. API 키가 없으면 실제 호출 사례를 건너뛴다.
이 스크립트에는 `--live` 옵션이 없으며 `RUN_LIVE_AI`로 호출을 제한하지 않는다.
`limit`의 문맥 길이·턴 수는 출력값이고, 통과 판정은 답변 없는 대화의 제외 여부에 적용된다.

## 검증 범위

| 파일 (`tests/`) | 검증 대상 |
|---|---|
| `test_auth_dependency.py` | 토큰 누락·만료·위조, 사용자 존재 여부, 인증 설정과 DB 오류 |
| `test_validation_errors.py` | 입력 경계값, 인증 실패·중복 가입, AI 실패 기록, DB 롤백, 오류 응답 형식 |
| `test_chat_api.py` | 화면·API 등록, 본인 기록 최신순 조회, 본인의 성공 기록만 문맥에 전달 |
| `test_async_chat.py` | AI 대기 중 DB 연결 반환, bcrypt 처리 중 다른 요청, 요청 취소, 롤백 후 재사용, DB 엔진 종료 |
| `test_logging.py` | 앱 처리 전 수신 로그, 요청 ID 연결·동시 요청 분리, 취소와 완료 구분, 민감정보 제외 |
| `test_ai_connect.py` | 문맥 순서·길이, AI 오류 분류·대체 모델 호출, 호출 시간 초과와 취소 전파 |
| `test_mysql_integration.py` | 초기 테이블과 ORM 일치, 5,000자·이모지·시간 정밀도, 외래키 제약 |
| `test_browser_integration.py` | 게스트 전송 차단, 로그인·질문·답변 표시·DB 저장·로그아웃 |
| `test_live_ai.py` | 실제 AI 응답과 테스트 DB 저장·조회 |
| `chat-api.test.mjs` | 토큰·질문 전송, 오류 안내, 취소와 시간 초과 구분 |

화면 대화방은 브라우저 저장소 기능이다. 서버 대화방 CRUD와 화면·서버 기록 동기화는 검증 범위에 포함되지 않는다.

## 실제 Compose 웹 검증

앱의 `.env`에 DB·인증·AI 설정이 필요하며 실제 질문은 외부 AI를 호출한다.

```powershell
docker compose up --build -d --wait
```

| 대상 | 주소 |
|---|---|
| 웹 화면 | <http://127.0.0.1:8000> |
| API 문서 | <http://127.0.0.1:8000/docs> |

| 입력·작업 | 판정 조건 |
|---|---|
| 게스트 질문 전송 | 로그인 안내 표시, 채팅 요청 미전송 |
| 회원가입·로그인 | HTTP 200, 사용자 ID 표시 |
| 로그인 후 질문 전송 | HTTP 200, `answer`, `request_id`, `created_at` 반환 및 답변 표시 |
| 채팅 응답 비교 | 본문의 `request_id`와 응답 헤더 `X-Request-ID` 일치 |
| `/docs`에서 로그인 토큰으로 `GET /api/me/chats` 호출 | 본인 기록만 조회, 성공 기록의 `status`는 `success` |
| 로그아웃 | 사용자 ID와 해당 계정의 화면 대화 숨김 |
| 브라우저 Console | JavaScript 실행 오류 없음 |

화면은 기록 조회 API를 호출하지 않으므로 API 검증을 별도로 수행한다.

### 로그·저장 기록 조회

```powershell
docker compose logs -f backend
docker compose exec db mysql -uroot -p
```

SQL 조회 대상은 `.env`의 `MYSQL_DATABASE`에 지정된 DB다.
`scripts/check_logs.sql`은 테이블 구조, 대화 기록, 오류·응답 시간 집계를 조회한다.
쿼리의 사용자 ID와 요청 ID는 검증 대상 값으로 지정한다.
서버 로그와 저장 기록의 연결 키는 `request_id`다.

## 판정 조건

| 결과 | 의미 |
|---|---|
| pytest 종료 코드 `0`, 필수 테스트 실행, 실패·수집 오류 없음 | 선택한 범위 통과 |
| `MYSQL_TEST_URL` 미설정에 따른 `skipped` | DB 검증 미실시 |
| `RUN_BROWSER_TESTS`가 `1`이 아닌 경우의 `skipped` | 브라우저 검증 미실시 |
| `RUN_LIVE_AI`가 `1`이 아닌 경우의 `skipped` | 실제 AI pytest 미실시 |
| `-m 'not live_ai'`의 `deselected` | 실제 AI 테스트를 선택 대상에서 제외 |
| JS 테스트의 실패 `0`, 종료 코드 `0` | 요청 유틸리티 검증 통과 |
| AI 스모크의 선택한 사례 `PASS`, 종료 코드 `0` | 선택한 스모크 범위 통과. 건너뛴 사례는 미검증 |

DB 접속 실패 확인 항목은 Docker 실행 상태, `db-test` 상태, 13307 포트 충돌이다.
실제 AI 호출이 기본 pytest에서 차단되면 해당 테스트의 AI 모킹을 확인한다.

## 종료 절차

성공·실패 여부와 관계없이 동일한 프로젝트 이름과 Compose 파일로 전용 테스트 DB를 종료한다.

```powershell
docker compose -p chatbot-validation-test -f docker-compose.test.yml down
Remove-Item Env:MYSQL_TEST_URL, Env:RUN_BROWSER_TESTS, Env:RUN_LIVE_AI -ErrorAction SilentlyContinue
```

종료 대상은 전용 테스트 프로젝트이며 앱 Compose와 개발 DB는 포함하지 않는다.
fixture 종료 후 테스트 기록이 없는 것은 정상이다.

## 관련 문서

- [리팩터링 문서](refactoring.md)
- [API 명세와 앱 실행](../README.md)
