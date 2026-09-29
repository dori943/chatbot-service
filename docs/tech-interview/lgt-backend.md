# 백엔드 예상 문답 — 인증·API·DB·통합

[전체 학습 안내](README.md)

대상 역할은 협업 문서에 백엔드로 기재된 **방승규·이건탁**입니다. 아래 묶음은 학습 순서이며, 두 사람의 실제 작업 분담을 뜻하지 않습니다. 개인 기여 질문에서는 본인의 커밋과 PR로 확인한 작업만 답하세요.

기준은 `refactor/bsg-back/app-refactoring` 브랜치의 `fcbb7e5c82c59996d92fd77c258b8e02fbfd2da3`입니다. 코드와 테스트 내용을 읽어 작성했으며, 아래 테스트명은 확인 경로를 가리킵니다. 이번 문답 작성 과정에서 테스트를 실행한 것은 아닙니다.

## 인증·API

### B01. FastAPI에서 요청이 실제 처리 함수까지 도달하는 과정을 설명해 주세요.

**답변:** `main.py`가 FastAPI 앱을 만들고 인증 라우터와 채팅 라우터를 등록합니다. `/api/chat` 요청은 채팅 라우터의 `send_chat()`으로 연결되고, FastAPI가 요청 본문과 인증·DB 의존성을 처리한 뒤 `chat_main.chat()`을 호출합니다. 라우터는 HTTP 연결을 담당하고, 서비스는 입력 검사·AI 호출·저장을 진행하도록 역할을 나눴습니다.

**꼬리 질문:** `Depends()`는 단순히 함수 실행을 줄여 쓰는 문법인가요?  
**짧은 답:** 필요한 값을 FastAPI가 준비하고 주입하게 만드는 장치입니다. 여기서는 인증된 사용자 ID와 DB 세션을 공급하며, 테스트에서는 DB 의존성을 교체할 수도 있습니다.

**코드 근거:** [앱과 라우터 등록](../../app/main.py), [send_chat](../../app/routers/chat.py), [get_token_id](../../app/core/dependencies.py).  
**테스트 근거:** [test_home_and_openapi_start, test_auth_required_before_ai](../../tests/test_chat_api.py).

### B02. Pydantic 모델, dataclass, SQLAlchemy 모델은 각각 무엇을 하나요?

**답변:** `ChatRequest`와 `AuthRequest`는 Pydantic 모델로, HTTP 요청에서 필요한 필드와 자료형을 정의합니다. `AIResult`는 AI 모듈과 서비스 사이에 결과를 전달하는 dataclass이며, 선언된 타입만으로 런타임 검증이 자동 보장되지는 않습니다. `ChatLog`와 `Login`은 SQLAlchemy 모델로 DB 테이블·열·키를 표현합니다. 그래서 AI 결과는 `validate_result()`에서 별도로 검사하고, DB 저장에는 ORM 모델을 사용합니다.

**꼬리 질문:** `AIResult` 전체가 사용자에게 그대로 반환되나요?  
**짧은 답:** 아닙니다. `chat_main.chat()`이 성공 응답 딕셔너리를 따로 만들기 때문에 내부 모델명이나 모든 진단 정보가 그대로 노출되지는 않습니다.

**코드 근거:** [ChatRequest와 AIResult](../../app/schemas/chat.py), [AuthRequest](../../app/schemas/auth.py), [ChatLog](../../app/models/chatlog.py), [validate_result](../../app/services/chat_main.py).

### B03. 핵심 API의 요청과 성공 응답을 설명해 주세요.

**답변:** 회원가입과 로그인은 각각 `/auth/register`, `/auth/login`으로 `id`와 `pw`를 POST합니다. 채팅은 `/api/chat`에 `room_id`, `room_name`, `question`을 보내고 Bearer 토큰으로 인증합니다. 성공하면 방 정보·답변·요청 ID·저장 시각을 받으며, `GET /api/me/chats`는 로그인한 사용자의 대화 목록을 반환합니다. 현재 이 네 API의 성공 상태 코드는 모두 200입니다.

| API | 요청 | 성공 응답 핵심 |
|---|---|---|
| `POST /auth/register` | `{"id":"study-user","pw":"sample-password"}` | `{"message":"register success"}` |
| `POST /auth/login` | 위와 같은 필드 | `message`, `token`, `token_type: "bearer"` |
| `POST /api/chat` | `{"room_id":"room-a","room_name":"시험 준비","question":"인증이 뭐야?"}` | `room_id`, `room_name`, `answer`, `request_id`, `created_at` |
| `GET /api/me/chats` | `Authorization: Bearer <token>` | 각 항목에 `id`, 방 정보, `question`, `answer`, `status`, `created_at` |

**꼬리 질문:** 회원가입 성공은 무조건 201이라고 답하면 되나요?  
**짧은 답:** 현재 라우터에는 201 지정이 없어 200입니다. API 설계 관례와 현재 구현을 구분해서 설명해야 합니다.

**코드 근거:** [인증 라우터](../../app/routers/auth.py), [채팅 라우터](../../app/routers/chat.py), [인증 응답](../../app/services/auth.py), [채팅 응답](../../app/services/chat_main.py).  
**테스트 근거:** [test_register_login_and_unpaginated_history, test_chat_releases_db_while_waiting_and_returns_saved_timestamp](../../tests/test_async_chat.py).

### B04. 잘못된 입력은 어디서 차단하며, 프론트 검사만으로 충분한가요?

**답변:** 누락된 필드나 잘못된 자료형은 Pydantic이 검사하고, 공백·길이 같은 규칙은 서비스에서 검사합니다. 채팅은 앞뒤 공백을 제거한 뒤 방 ID는 64자, 방 이름은 100자, 질문은 설정값과 5,000자 중 작은 값까지 허용합니다. 브라우저 검사는 직접 API를 호출하면 우회할 수 있으므로 서버 검사도 필요하며, 잘못된 입력은 AI 호출과 대화 저장 전에 422로 거절합니다.

**꼬리 질문:** 한글 비밀번호 30자와 질문 30자는 같은 길이 기준인가요?  
**짧은 답:** 아닙니다. 질문은 문자열 길이로 검사하지만 비밀번호는 bcrypt 입력 제한에 맞춰 UTF-8 인코딩 후 72바이트 이내인지 검사합니다.

**코드 근거:** [채팅 입력 검사 함수들](../../app/services/chat_main.py), [validate_auth](../../app/services/auth.py), [validation_error_handler](../../app/core/errors.py).  
**테스트 근거:** [test_invalid_question_is_rejected_before_ai, test_invalid_room_is_rejected_before_ai, test_question_boundary_normalization_and_configured_limit](../../tests/test_validation_errors.py).

### B05. 회원가입 시 비밀번호를 어떻게 저장하나요?

**답변:** 비밀번호 원문 대신 bcrypt가 salt를 포함해 생성한 해시를 저장하고, 로그인 때 `checkpw()`로 일치 여부를 확인합니다. 아이디는 앞뒤 공백을 제거하지만 비밀번호는 공백만 있는지 검사할 뿐 실제 값의 앞뒤 공백을 제거하지 않습니다. UTF-8 기준 72바이트 제한을 검사하며, 시간이 걸리는 해싱과 검증은 스레드풀에서 실행해 이벤트 루프가 오래 막히지 않도록 했습니다.

**꼬리 질문:** 중복 아이디 가입 요청이 동시에 들어오면 어떻게 처리하나요?  
**짧은 답:** `login.id`의 기본키 제약이 중복 저장을 막고, 회원가입 서비스는 MySQL 중복 키 오류를 409 `USER_ALREADY_EXISTS`로 변환합니다.

**코드 근거:** [register·validate_auth·login](../../app/services/auth.py), [hash_password·verify_password](../../app/utils/security.py), [Login](../../app/models/login.py).  
**테스트 근거:** [test_auth_boundaries_duplicate_and_wrong_credentials, test_auth_normalizes_id_without_changing_password](../../tests/test_validation_errors.py), [test_password_hashing_allows_other_requests_to_progress](../../tests/test_async_chat.py).

### B06. 로그인 성공 후 JWT를 발급하는 이유와 토큰 내용을 설명해 주세요.

**답변:** 로그인할 때 DB의 비밀번호 해시와 입력을 비교하고, 성공하면 사용자 ID와 만료 시각이 담긴 JWT를 발급합니다. 이후 API 요청마다 비밀번호를 다시 보내는 대신 `Authorization: Bearer` 헤더에 이 토큰을 보냅니다. 현재 코드는 `SECRET_KEY`로 HS256 서명을 만들고 만료 시간을 60분으로 정하며, 서명은 위변조 검증을 위한 것으로 내용 암호화를 뜻하지 않습니다.

**꼬리 질문:** JWT에 비밀번호나 API 키를 넣어도 서명되어 있으니 안전한가요?  
**짧은 답:** 안 됩니다. payload는 읽을 수 있으므로 민감정보를 넣지 않아야 하며, 현재 payload는 `id`와 `exp`만 담습니다.

**코드 근거:** [login](../../app/services/auth.py), [create_token·ALGORITHM·TOKEN_EXP](../../app/utils/security.py).

### B07. 로그인 화면을 통과한 사람만 채팅할 수 있게 하는 실제 보안 장치는 무엇인가요?

**답변:** 채팅과 내 로그 API에 연결된 `get_token_id()`가 서버에서 인증을 강제합니다. 토큰 서명과 만료를 확인하고 `id`, `exp` 존재 여부, ID 형식, DB의 사용자 존재 여부까지 검사합니다. 토큰이 없거나 잘못되면 401이므로 브라우저 화면을 우회해 직접 요청하더라도 보호된 기능을 사용할 수 없습니다.

**꼬리 질문:** 사용자 확인 중 DB가 고장 나면 401인가요?  
**짧은 답:** DB 장애는 503 `DB_UNAVAILABLE`입니다. 인증 정보가 잘못된 경우와 인증을 확인할 수 없는 경우를 구분하고, 서명 키가 없으면 503 `AUTH_UNAVAILABLE`을 반환합니다.

**코드 근거:** [get_token_id](../../app/core/dependencies.py), [check_user](../../app/services/auth.py), [보호된 채팅 라우터](../../app/routers/chat.py).  
**테스트 근거:** [test_rejects_invalid_identity, test_database_failure_is_not_an_invalid_login, test_unconfigured_auth_service, test_invalid_token_does_not_query_user](../../tests/test_auth_dependency.py).

### B08. 다른 사용자 ID나 같은 방 ID를 보내면 다른 사람의 대화를 볼 수 있나요?

**답변:** 대화의 소유자는 요청 본문이나 쿼리의 `user_id`가 아니라 검증된 토큰에서 결정합니다. 로그 목록은 그 사용자 ID로 조회하고, AI 문맥은 사용자 ID와 방 ID를 함께 조건으로 사용합니다. 그래서 다른 사람이 같은 `room_id`를 쓰더라도 문맥이 합쳐지지 않으며, 요청에 다른 사용자 ID를 추가해도 저장 주체가 바뀌지 않습니다.

**꼬리 질문:** 방 ID가 같으면 그룹 채팅 기능이라고 설명해도 되나요?  
**짧은 답:** 아닙니다. 현재는 사용자 내부에서 문맥을 나누는 값이며, 공유 방이나 참여자 권한 모델은 구현되어 있지 않습니다.

**코드 근거:** [get_history·get_list_chat](../../app/services/chat_db.py), [토큰에서 주입하는 user_id](../../app/routers/chat.py), [ChatLog](../../app/models/chatlog.py).  
**테스트 근거:** [test_history_is_owned_and_ordered_without_pagination, test_context_contains_only_own_room_successful_turns_in_chronological_order](../../tests/test_chat_api.py), [test_question_boundary_normalization_and_configured_limit](../../tests/test_validation_errors.py).

### B09. 오류 응답 형식을 통일한 이유와 주요 상태 코드를 설명해 주세요.

**답변:** 프론트에서 일관되게 안내하도록 인증·입력 검증·서비스 오류를 `error_code`, `message`, `request_id` 형식으로 통일했습니다. 인증 실패는 401, 입력 오류는 422, AI 타임아웃은 504, AI 요청 제한은 429, DB 장애는 503으로 구분합니다. AI의 그 밖의 여러 실패는 기본 502로 처리하고, 처리하지 못한 일반 예외는 500으로 바꾸며 외부 API나 SQL의 예외 원문은 사용자 메시지에 그대로 넣지 않습니다. 다만 404·405처럼 프레임워크가 직접 반환하는 HTTP 오류는 기본 `detail` 형식입니다.

**꼬리 질문:** AI가 성공이라고 해도 답변이 비어 있으면 200인가요?  
**짧은 답:** 아닙니다. `validate_result()`가 빈 답변이나 문자열이 아닌 답변을 실패로 바꾸고, 5,000자를 넘는 답변도 별도 오류로 처리합니다.

**코드 근거:** [APIError·공통 예외 처리·AI_ERROR_STATUS](../../app/core/errors.py), [validate_result](../../app/services/chat_main.py), [예외 처리기 등록](../../app/main.py).  
**테스트 근거:** [test_ai_failure_is_saved_before_error_response, test_invalid_ai_answer_is_not_saved_as_success, test_malformed_json_uses_common_error_format](../../tests/test_validation_errors.py).

## DB·서비스 통합

### B10. 과제에서는 SQLite를 권장하는데 현재 서비스는 어떤 DB를 사용하나요?

**답변:** 현재 실행 경로는 MySQL이며, SQLAlchemy의 비동기 엔진과 `aiomysql` 드라이버를 사용합니다. 과제의 SQLite는 권장사항이므로 MySQL을 사용했다는 사실만으로 요구사항을 위반한 것은 아니지만, 평가자가 연결하고 로그를 확인할 수 있는 실행·조회 방법은 제공해야 합니다. 현재 DB를 사용하는 자동 테스트도 별도 MySQL을 사용하며, 실제 실행 DB는 `app/db.py`의 연결 구성을 기준으로 설명합니다.

**꼬리 질문:** MySQL을 고른 이유를 묻는다면 어떻게 답하나요?  
**짧은 답:** SQLAlchemy 모델과 외래키를 사용해 사용자·로그를 저장하는 현재 구조를 설명하고, 선택 당시의 팀 의사결정은 실제 기록으로 확인한 이유만 말합니다. 코드만 보고 팀의 선택 이유를 만들어 말하지 않습니다.

**코드 근거:** [DATABASE_URL·engine](../../app/db.py), [테이블 초기화 SQL](../../data/init.sql).  
**테스트 근거:** [전용 MySQL fixture](../../tests/conftest.py), [test_init_sql_matches_orm](../../tests/test_mysql_integration.py). SQLite 권장은 제공된 과제 명세에 근거합니다.

### B11. DB 테이블 관계와 로그의 주요 필드를 설명해 주세요.

**답변:** 사용자 테이블은 `login`, 대화 기록 테이블은 `chat_logs`이며 사용자 한 명에게 여러 대화 로그가 연결되는 구조입니다. `chat_logs.user_id`는 `login.id`를 참조하는 외래키라 존재하지 않는 사용자의 로그 저장을 DB에서도 막습니다. 로그에는 방 ID·이름, 질문·답변, 생성 시각 외에도 처리 상태·오류 코드·모델·지연 시간·요청 ID를 저장해 기능과 장애 추적을 함께 지원합니다.

**꼬리 질문:** `room_id`가 있으면 별도 방 테이블과 외래키도 있나요?  
**짧은 답:** 현재는 없습니다. 방 정보가 각 로그 행에 반복 저장되므로, 방 이름 일괄 변경이나 별도의 방 생명주기 관리는 추가 설계가 필요합니다.

**코드 근거:** [Login](../../app/models/login.py), [ChatLog](../../app/models/chatlog.py), [DDL](../../data/init.sql).  
**테스트 근거:** [test_init_sql_matches_orm, test_mysql_rejects_chat_for_missing_user](../../tests/test_mysql_integration.py).

### B12. 답변은 왜 NULL을 허용하고, 생성 시각은 어떻게 저장하나요?

**답변:** AI가 실패하면 정상 답변이 없으므로 `answer`는 NULL을 허용하고, 실패 원인은 `status`와 `error_code`로 구분합니다. 저장 시각은 서버에서 UTC로 만들고 MySQL의 `DATETIME(6)`에는 시간대 정보 없이 UTC 값으로 저장합니다. API에서는 그 값을 UTC로 해석해 `Z`로 끝나는 ISO 형식으로 반환하며, 채팅 성공 응답에도 실제 저장에 사용한 시각을 넣습니다.

**꼬리 질문:** DB의 `DATETIME` 자체가 UTC를 보장하나요?  
**짧은 답:** 아닙니다. 현재 애플리케이션의 저장·조회 규약이 UTC이므로, 다른 도구가 데이터를 넣을 때도 같은 규칙을 지켜야 합니다.

**코드 근거:** [ChatLog.answer·created_at](../../app/models/chatlog.py), [save_result](../../app/services/chat_db.py), [chat·get_my_chat의 시각 직렬화](../../app/services/chat_main.py).  
**테스트 근거:** [test_mysql_5000_character_boundary](../../tests/test_mysql_integration.py), [test_chat_releases_db_while_waiting_and_returns_saved_timestamp](../../tests/test_async_chat.py).

### B13. 질문 수신부터 응답 반환까지 실제 실행 순서를 설명해 주세요.

**답변:** 인증과 입력 검사를 통과하면 현재 사용자·방의 이전 성공 대화를 읽고, 그 문맥과 질문으로 AI를 호출합니다. AI 결과를 다시 검사한 뒤 DB에 먼저 저장하고, 성공 답변 또는 실패 오류 응답을 반환합니다. 따라서 현재 구현은 응답을 보낸 다음 백그라운드에서 저장하는 방식이 아니며, DB 저장에 실패하면 AI 답변이 생성됐어도 503을 반환합니다.

**꼬리 질문:** 모든 실패가 `chat_logs`에 저장되나요?  
**짧은 답:** 아닙니다. AI 실패·타임아웃은 저장 대상으로 만들지만 인증·입력 검증 실패는 저장 단계에 도달하지 않고, 요청 취소도 실패 행을 만들지 않습니다. DB 장애가 있으면 그 실패 행 자체를 저장할 수 없을 수도 있습니다.

**코드 근거:** [chat의 실행 순서](../../app/services/chat_main.py), [save_result](../../app/services/chat_db.py).  
**테스트 근거:** [test_ai_failure_is_saved_before_error_response, test_unexpected_ai_failures_are_recorded, test_save_failure_returns_503_and_rolls_back](../../tests/test_validation_errors.py), [test_cancelled_request_releases_session_without_saving_failure](../../tests/test_async_chat.py).

### B14. AI에 보낼 이전 대화는 어떻게 조회하고 정렬하나요?

**답변:** `get_history()`는 같은 사용자·같은 방이면서 `status`가 `success`인 대화만 조회합니다. ID 역순으로 최근 N개를 가져온 다음 목록을 뒤집어, AI에는 과거 질문·답변부터 최신 순서로 전달합니다. N은 `AI_CONTEXT_TURNS`로 설정하며 코드 기본값은 5턴입니다. 실패 기록은 사용자에게 보여 줄 로그에는 남지만, 정상 답변이 없으므로 AI 문맥 조회에서는 제외합니다.

**꼬리 질문:** 이 설계가 모든 대화를 기억하거나 동시에 보낸 질문의 순서를 보장하나요?  
**짧은 답:** 아닙니다. 제한된 최근 대화만 사용하고, 같은 방의 요청을 직렬화하는 별도 잠금도 없습니다. 동시에 보낸 질문은 서로의 아직 저장되지 않은 답변을 문맥에 포함하지 못할 수 있습니다.

**코드 근거:** [get_history](../../app/services/chat_db.py), [AI_CONTEXT_TURNS 기본값](../../app/core/config.py), [chat](../../app/services/chat_main.py).  
**테스트 근거:** [test_context_contains_only_own_room_successful_turns_in_chronological_order](../../tests/test_chat_api.py).

### B15. 내 대화 로그 조회 API는 무엇을 반환하고 어떤 한계가 있나요?

**답변:** `GET /api/me/chats`는 로그인한 사용자의 모든 방에 속한 로그를 생성 시각 내림차순, 같은 시각이면 ID 내림차순으로 반환합니다. 각 항목에는 질문·답변·상태·시각·방 정보가 있어 사용자 기준으로 대화를 확인할 수 있고, AI 실패 기록도 포함됩니다. 현재는 페이지네이션이나 방 필터가 없고 오류 코드·모델 같은 상세 진단 열도 이 API 응답에는 포함하지 않습니다.

**꼬리 질문:** 데이터가 많아지면 무엇을 개선하겠나요?  
**짧은 답:** 한 번에 모든 행을 반환하지 않도록 페이지 크기와 커서 조회를 설계하고, 실제 조회 조건과 실행 계획을 보고 인덱스를 검토하겠습니다. 이미 구현된 기능이라고 말해서는 안 됩니다.

**코드 근거:** [get_list_chat](../../app/services/chat_db.py), [get_my_chat](../../app/services/chat_main.py).  
**테스트 근거:** [test_history_is_owned_and_ordered_without_pagination, test_failed_answer_appears_in_history](../../tests/test_chat_api.py), [test_history_error_and_response_contract](../../tests/test_validation_errors.py).

### B16. 비동기 DB 세션은 어떻게 관리하고, AI를 기다리는 동안 연결은 어떻게 되나요?

**답변:** `get_db()`가 `async with SessionLocal()` 안에서 세션을 제공하고 요청 처리가 끝나면 정리합니다. 사용자 확인과 문맥 조회를 마친 뒤에는 `commit()`으로 읽기 트랜잭션도 끝내므로, AI 응답을 기다리는 동안 DB 연결을 계속 점유하지 않게 했습니다. AI 처리가 끝나면 같은 세션으로 저장 트랜잭션을 시작하고, DB 작업은 `await`로 호출합니다.

**꼬리 질문:** `async def`만 붙이면 모든 작업이 자동으로 비동기가 되나요?  
**짧은 답:** 아닙니다. 비동기 드라이버를 사용하고 기다리는 호출에 `await`를 써야 하며, bcrypt처럼 동기 방식으로 오래 실행되는 작업은 별도 스레드풀로 보내고 있습니다.

**코드 근거:** [SessionLocal·get_db](../../app/db.py), [check_user·login](../../app/services/auth.py), [get_history·save_result](../../app/services/chat_db.py).  
**테스트 근거:** [test_chat_releases_db_while_waiting_and_returns_saved_timestamp, test_password_hashing_allows_other_requests_to_progress, test_lifespan_disposes_database](../../tests/test_async_chat.py).

### B17. DB 작업에 실패하면 왜 rollback을 하며, 문맥 조회 실패도 바로 중단하나요?

**답변:** DB 작업에 실패하면 `rollback()`으로 진행 중인 트랜잭션을 정리해 같은 세션을 안전하게 다시 사용할 수 있게 합니다. 로그 저장과 내 로그 조회에 실패하면 503을 반환하지만, AI용 과거 문맥 조회 실패는 기록 후 빈 목록으로 반환해 새 질문 처리를 계속 시도합니다. 이것은 문맥 없이도 현재 질문에 답할 수 있게 하는 선택이며, DB가 계속 불가능하면 뒤의 저장 단계에서 결국 503이 발생할 수 있습니다.

**꼬리 질문:** AI 요청까지 포함해 DB 트랜잭션 하나로 묶으면 전체가 원자적으로 취소되나요?  
**짧은 답:** 외부 AI 호출은 DB 트랜잭션에 포함되지 않습니다. DB rollback이 이미 실행된 AI 호출이나 비용을 되돌리지는 못하며, 현재는 AI 대기 전 읽기 트랜잭션을 끝내도록 구현되어 있습니다.

**코드 근거:** [get_history·get_list_chat·save_result의 예외 처리](../../app/services/chat_db.py), [인증 DB 오류 처리](../../app/services/auth.py).  
**테스트 근거:** [test_history_failure_rolls_back_before_reusing_session](../../tests/test_async_chat.py), [test_save_failure_returns_503_and_rolls_back](../../tests/test_validation_errors.py).

### B18. 장애 한 건을 어떻게 추적하고, 구현을 어떤 테스트로 입증하나요?

**답변:** 요청마다 서버가 요청 ID를 만들고 `ContextVar`로 전달해 서버 로그·응답 헤더·대화 DB 행을 같은 ID로 연결합니다. 예외는 종류와 발생 위치를 기록하되 질문·비밀번호·토큰·SQL 파라미터 같은 원문을 로그에 노출하지 않도록 구성했습니다. 인증 거절·사용자 및 방 격리·실패 저장·DB 연결 반환을 검사하는 테스트와 실제 MySQL 제약을 검사하는 테스트가 있으며, 실행 결과를 제시할 때는 현재 브랜치에서 실행했는지 별도로 확인해야 합니다.

**꼬리 질문:** 테스트 파일이 있다는 것만으로 실제 AI 연동과 배포까지 통과했다고 할 수 있나요?  
**짧은 답:** 안 됩니다. 일반 API 테스트는 AI를 mock으로 대체하고 전용 MySQL 설정이 없으면 DB 관련 테스트가 건너뛰어질 수 있으므로, 실제 AI·브라우저·외부 URL 검증 결과는 각각 따로 제시해야 합니다.

**코드 근거:** [RequestLoggingMiddleware·log_event](../../app/core/logging.py), [API 오류 응답 ID](../../app/core/errors.py), [DB에 저장하는 request_id](../../app/services/chat_db.py).  
**테스트 근거:** [test_chat_request_id_matches_logs_response_and_database, test_concurrent_requests_keep_separate_log_contexts, test_error_logs_have_request_id_without_sensitive_details](../../tests/test_logging.py), [테스트 DB와 AI mock 설정](../../tests/conftest.py).
