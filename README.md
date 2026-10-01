# chatbot-service ( 작성중 )

FastAPI에서 화면과 API를 함께 제공하는 AI 챗봇입니다. 회원가입·로그인, 질문·답변,
성공·실패 기록 저장, 본인 기록 조회와 사용자·대화방별 최근 대화 문맥을 제공합니다.

- [테스트 가이드](docs/testing-guide.md): MySQL·브라우저·오프라인 AI 검증 실행 방법
- [develop 대비 리팩터링](docs/refactoring.md): 폴더별 책임과 백엔드·프론트엔드·AI 변경 범위

## 실행

1. `.env`가 없으면 `.env.example`을 복사합니다. 기존 파일은 유지합니다.
2. MySQL 설정, `SECRET_KEY`, `AI_API_KEY`를 입력합니다.
3. 프로젝트 루트에서 실행합니다.

```sh
docker compose up --build -d --wait
docker compose ps
docker compose logs -f backend
```

화면: <http://127.0.0.1:8000> / API 문서: <http://127.0.0.1:8000/docs>

앱의 DB 호스트는 Compose 서비스 이름인 `db`입니다. `.env`는 Compose가 주입하며,
일반 앱 실행 시 Python이 직접 읽지 않습니다. 인증 토큰 유효기간은 현재 60분입니다.

`data/init.sql`은 빈 MySQL 데이터 디렉터리를 처음 만들 때만 실행됩니다.
기존 볼륨은 재빌드·재시작으로 초기화되지 않습니다. 이번 변경은 `chat_logs.room_id`, `room_name` 필수 컬럼을 추가합니다.
기존 개발 DB를 새 정의로 초기화하려면 아래 명령을 실행합니다. **기존 계정과 대화 기록이 삭제됩니다.**

```sh
docker compose down --volumes
docker compose up --build -d --wait
```

자동 테스트는 개발 DB와 별도인 전용 MySQL을 사용합니다.

## API

| 메서드 | 경로 | 요청·응답 | 인증 |
|---|---|---|---|
| POST | `/auth/register` | `{ "id": "...", "pw": "..." }` → 성공 메시지 | 없음 |
| POST | `/auth/login` | 같은 요청 → `message`, `token`, `token_type` | 없음 |
| POST | `/api/chat` | `{ "room_id": "...", "room_name": "...", "question": "..." }` → `id`, `room_id`, `room_name`, `answer`, `request_id`, `created_at` | Bearer 토큰 |
| GET | `/api/me/chats` | 본인 전체 기록 배열, 최신순 | Bearer 토큰 |
| GET | `/api/me/rooms` | 질문이 저장된 방의 `room_id`, `room_name` 배열, 최근 저장순 | Bearer 토큰 |
| GET | `/api/me/chats?room_id=...` | 해당 방의 처리 중·성공·실패 기록 배열, 최신순 | Bearer 토큰 |
| DELETE | `/api/me/chats?room_id=...` | 본인의 해당 방 기록 전체 삭제 → `{ "deleted": 삭제 건수 }` | Bearer 토큰 |

채팅 인증 헤더는 `Authorization: Bearer <로그인 응답의 token>`입니다.
사용자 ID는 토큰에서 가져옵니다. 요청에 추가한 `user_id` 등 정의되지 않은 필드는 무시합니다.
`room_id`는 프론트가 생성한 대화방 ID입니다. 같은 방에서는 같은 값을 보내며 새 방에서는 새 값을 보냅니다.
서비스에서 앞뒤 공백을 제거한 뒤 1~64자를 허용합니다. 다른 사용자와 같은 방 ID를 보내도 문맥은 공유되지 않습니다.
방 ID 비교는 DB 기본 대조 규칙을 따릅니다. 현재 Compose 설정에서는 대소문자를 구분하지 않습니다.
`room_name`은 화면의 방 이름이며 앞뒤 공백 제거 후 1~100자를 허용합니다.
프론트는 첫 질문의 앞 30자로 제목을 만들고, 같은 방의 후속 요청에도 해당 제목을 보냅니다.

채팅 성공 응답은 HTTP 200입니다.

```json
{
  "id": 1,
  "room_id": "room-example",
  "room_name": "FastAPI란?",
  "answer": "FastAPI는 파이썬으로 API를 만드는 프레임워크입니다.",
  "request_id": "요청별 식별자",
  "created_at": "2026-09-24T07:00:00Z"
}
```

기록 조회는 `[{ "id": 1, "room_id": "room-example", "room_name": "FastAPI란?", "question": "...", "answer": "...", "status": "success", "error_code": null, "created_at": "...Z" }]`
형식입니다. `status`는 `processing`, `success`, `error`, `timeout`이며 처리 중·실패 기록의 `answer`는 `null`입니다.
페이지네이션과 `items`·`total` 래핑은 사용하지 않습니다. `room_id`를 지정하면 해당 방만 조회하며, 방 이름은 마지막 질문 기록을 기준으로 합니다.
삭제는 처리 상태와 관계없이 본인의 해당 방 기록 전체에 적용됩니다. 존재하지 않는 방은 `deleted: 0`을 반환합니다.
삭제 후 `chat_room_deleted` 로그에 사용자 ID, 방 ID, 건수, 요청 ID를 남기며 질문·답변 본문은 기록하지 않습니다.

인증·입력 검증·서비스 오류는 다음 형식으로 반환합니다. 같은 요청의 ID는 응답 헤더
`X-Request-ID`, 서버 로그, 저장된 채팅 기록에 연결됩니다.

```json
{ "error_code": "UNAUTHORIZED", "message": "로그인이 필요합니다. 다시 로그인해 주세요.", "request_id": "요청별 식별자" }
```

| HTTP | 대표 오류 |
|---|---|
| 401 | `UNAUTHORIZED`: 로그인 실패, 토큰 누락·만료·위조, 존재하지 않는 사용자 |
| 409 | `USER_ALREADY_EXISTS`: 중복 회원가입 / `CHAT_CLOSED`: 결과 저장 전에 이미 종료되거나 삭제된 대화 |
| 422 | `INVALID_INPUT`: 요청 검증 실패 / `AI_BLOCKED`: AI 차단 |
| 429 | `AI_RATE_LIMIT`: AI 요청 제한 |
| 500 | `INTERNAL_ERROR`: 처리하지 못한 내부 오류 |
| 502 | AI 연결·응답 오류, `AI_ANSWER_TOO_LONG`, `AI_TOKEN_LIMIT`: 생성 한도로 잘린 응답 등 |
| 503 | `DB_UNAVAILABLE`: DB 실패 / `AUTH_UNAVAILABLE`: 인증 설정·저장된 인증 정보 문제 / `AI_CONFIG_ERROR`: AI 키·권한 설정 문제 |
| 504 | `AI_TIMEOUT`: AI 응답 시간 초과 |

404·405 등 프레임워크가 직접 반환하는 HTTP 오류는 기본 `detail` 형식입니다.
내용 검증 규칙은 서비스에 있으므로 Swagger 스키마에는 타입 중심으로 표시됩니다.

## 현재 동작 범위

- 질문은 앞뒤 공백을 제거한 뒤 `min(MAX_QUESTION_LENGTH, 5000)`자까지 허용합니다.
- AI 답변이 비었거나 5,000자를 넘으면 실패 기록을 저장하고 오류를 반환합니다. 답변을 잘라 저장하지 않습니다.
- 실제 답변 길이는 `AI_MAX_TOKENS`(기본 800, 한국어 기준 대략 400~600자)가 먼저 제한합니다.
  한도에 걸려 잘린 답변은 저장하지 않고 `AI_TOKEN_LIMIT`으로 반환하므로, 긴 답변이 필요하면 이 값을 올려야 합니다.
- AI 호출 1회 제한 시간(`AI_TIMEOUT_SECONDS`)의 하한은 10초입니다. 제공사가 그보다 짧은 deadline을
  400으로 거부하므로, 남은 예산이 10초 미만이면 폴백 모델을 호출하지 않고 건너뜁니다.
- AI가 `MAX_TOKENS`로 종료하면 부분 답변도 성공으로 반환하지 않습니다. 키 누락·키 인증·권한 오류와 함께 재시도·폴백 없이 실패 기록을 저장하고 설정 확인 안내를 반환합니다.
- 인증·입력 검증 실패는 AI를 호출하거나 채팅 기록을 만들지 않습니다. DB 저장 실패는 503입니다.
- 검증을 통과한 질문은 AI 호출 전에 `processing`으로 저장·커밋하며, 완료 시 같은 DB `id`의 답변·상태를 갱신합니다. `created_at`은 질문 저장 시각입니다.
- 서버 작업 취소는 `error`로 기록합니다. 서버 강제 종료·결과 저장 실패로 남은 `processing`은 생성 후 `AI_TOTAL_TIMEOUT_SECONDS + 30`초가 지난 뒤 본인 목록·기록 조회 시 `error / INTERNAL_ERROR`로 종료합니다. 중단된 AI 작업을 자동 재실행하지 않습니다.
- DB 시각은 UTC이며 API에서는 `Z`를 붙여 반환합니다.
- AI 문맥은 **같은 사용자·같은 방의 최근 성공 대화**입니다. 기본 5턴에서 길이에 따라 오래된 대화를 더 제외합니다.
- 로그인·새로고침·답변 완료 시 서버에서 방 목록을 갱신하고, 방 선택·답변 완료 시 해당 방의 모든 처리 상태를 조회합니다. 다른 브라우저에서도 같은 계정의 기록을 복원합니다.
- 선택한 방은 URL의 `#room=...`으로 복원합니다. 서버에 접수된 질문은 페이지 새로고침·방 전환 이후에도 처리되며, 현재 방이 처리 중이고 기존 POST 응답을 기다리는 상태가 아니면 2초 간격으로 기록을 조회합니다. 완료·실패·방 전환·로그아웃 시 해당 조회를 중단합니다.
- `localStorage`에는 계정별 방 ID·이름만 최근 30개까지 보관합니다. 서버에서 받은 방 목록 전체는 화면에 표시하며 질문·답변은 브라우저 저장소에 저장하지 않습니다. 이전 형식의 본문은 해당 계정의 저장 목록을 읽을 때 제거합니다.
- 방 삭제는 DB 기록 삭제 성공 후 화면에 반영합니다. 다른 브라우저에는 다음 목록·기록 조회 시 반영됩니다.
- 대기 중지는 브라우저의 응답 대기·상태 조회만 멈춥니다. 서버 처리는 유지하며 방 재선택 시 상태를 다시 조회합니다. 실패한 질문은 기록에 남고, 화면에서는 AI 오류와 서버 오류로 구분해 표시합니다.
- 질문을 자동 재전송하지 않습니다. 실패 기록의 다시 시도는 새 질문 기록을 만들며, 동일 POST의 중복 접수를 막는 멱등성 키는 사용하지 않습니다.
- 방 이름은 각 대화 기록에 요청 당시 값으로 저장합니다. 방 이름 변경 API는 구현하지 않았습니다.
- JWT 만료 또는 채팅 요청의 401 응답 시 토큰을 정리하고 화면을 비로그인 상태로 갱신합니다. AI 오류인 502·503 응답은 로그인 상태를 유지합니다.

## 테스트

기본 pytest는 실제 AI를 호출하지 않습니다. API·DB 테스트는 별도 MySQL 컨테이너를 사용합니다.
전용 DB를 지정하지 않으면 해당 테스트는 건너뛰므로 [테스트 가이드](docs/testing-guide.md)의 전체 실행 절차를 따르세요.

```sh
python scripts/ai_smoke_test.py validation limit fallback
node --test tests/*.test.mjs
```

스모크는 기존 여섯 사례를 직접 실행합니다. 인자 없이 실행하면 API 키가 있는 경우
실제 AI 호출도 포함하므로, 오프라인 검증에는 위처럼 사례를 지정합니다.
2026-09-28 검증 결과: 전용 MySQL·Chromium을 포함한 pytest 156개, JS 테스트 11개,
오프라인 AI 스모크 3개 시나리오가 통과했습니다. 실제 AI 호출 테스트 1개는 제외했으며,
외부 배포 환경은 이번 검증에 포함하지 않았습니다. 개발용 Compose의 컨테이너·DB 볼륨을
재생성한 뒤 웹페이지 접속·가입·로그인·방 ID 전송·입력 검증도 확인했습니다.
