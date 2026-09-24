# chatbot-service ( 작성중 )

FastAPI에서 화면과 API를 함께 제공하는 AI 챗봇입니다. 회원가입·로그인, 질문·답변,
성공·실패 기록 저장, 본인 기록 조회와 사용자별 최근 대화 문맥을 제공합니다.

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
기존 볼륨은 재빌드·재시작으로 초기화되지 않으며, 이번 리팩터링에 따른 스키마 변경은 없습니다.
자동 테스트는 개발 DB와 별도인 전용 MySQL을 사용합니다.

## API

| 메서드 | 경로 | 요청·응답 | 인증 |
|---|---|---|---|
| POST | `/auth/register` | `{ "id": "...", "pw": "..." }` → 성공 메시지 | 없음 |
| POST | `/auth/login` | 같은 요청 → `message`, `token`, `token_type` | 없음 |
| POST | `/api/chat` | `{ "question": "..." }` → `answer`, `request_id`, `created_at` | Bearer 토큰 |
| GET | `/api/me/chats` | 본인 전체 기록 배열, 최신순 | Bearer 토큰 |

채팅 인증 헤더는 `Authorization: Bearer <로그인 응답의 token>`입니다.
사용자 ID는 토큰에서 가져옵니다. 요청에 추가한 `user_id` 등 정의되지 않은 필드는 무시합니다.

채팅 성공 응답은 HTTP 200입니다.

```json
{
  "answer": "FastAPI는 파이썬으로 API를 만드는 프레임워크입니다.",
  "request_id": "요청별 식별자",
  "created_at": "2026-09-24T07:00:00Z"
}
```

기록 조회는 `[{ "id": 1, "question": "...", "answer": "...", "status": "success", "created_at": "...Z" }]`
형식입니다. 실패 기록의 `answer`는 `null`입니다. 페이지네이션과 `items`·`total` 래핑은 사용하지 않습니다.

인증·입력 검증·서비스 오류는 다음 형식으로 반환합니다. 같은 요청의 ID는 응답 헤더
`X-Request-ID`, 서버 로그, 저장된 채팅 기록에 연결됩니다.

```json
{ "error_code": "UNAUTHORIZED", "message": "로그인이 필요합니다. 다시 로그인해 주세요.", "request_id": "요청별 식별자" }
```

| HTTP | 대표 오류 |
|---|---|
| 401 | `UNAUTHORIZED`: 로그인 실패, 토큰 누락·만료·위조, 존재하지 않는 사용자 |
| 409 | `USER_ALREADY_EXISTS`: 중복 회원가입 |
| 422 | `INVALID_INPUT`: 요청 검증 실패 / `AI_BLOCKED`: AI 차단 |
| 429 | `AI_RATE_LIMIT`: AI 요청 제한 |
| 500 | `INTERNAL_ERROR`: 처리하지 못한 내부 오류 |
| 502 | AI 연결·응답 오류, `AI_ANSWER_TOO_LONG` 등 |
| 503 | `DB_UNAVAILABLE`: DB 실패 / `AUTH_UNAVAILABLE`: 인증 설정·저장된 인증 정보 문제 |
| 504 | `AI_TIMEOUT`: AI 응답 시간 초과 |

404·405 등 프레임워크가 직접 반환하는 HTTP 오류는 기본 `detail` 형식입니다.
내용 검증 규칙은 서비스에 있으므로 Swagger 스키마에는 타입 중심으로 표시됩니다.

## 현재 동작 범위

- 질문은 앞뒤 공백을 제거한 뒤 `min(MAX_QUESTION_LENGTH, 5000)`자까지 허용합니다.
- AI 답변이 비었거나 5,000자를 넘으면 실패 기록을 저장하고 오류를 반환합니다. 답변을 잘라 저장하지 않습니다.
- 인증·입력 검증 실패는 AI를 호출하거나 채팅 기록을 만들지 않습니다. DB 저장 실패는 503입니다.
- DB 시각은 UTC이며 API에서는 `Z`를 붙여 반환합니다.
- AI 문맥은 **같은 사용자의 최근 성공 대화**입니다. 기본 5턴에서 길이에 따라 오래된 대화를 더 제외합니다.
- 화면의 대화방 생성·삭제는 브라우저 저장소에서 동작합니다. 서버에 대화방 CRUD는 없으며 새 방을 만들어도 서버 문맥이 초기화되지 않습니다.
- 화면은 DB 기록 조회 API와 동기화되지 않습니다. 중지 버튼은 브라우저의 응답 대기를 취소하며 서버 처리 취소까지 보장하지 않습니다.

## 테스트

기본 pytest는 실제 AI를 호출하지 않습니다. API·DB 테스트는 별도 MySQL 컨테이너를 사용합니다.
전용 DB를 지정하지 않으면 해당 테스트는 건너뛰므로 [테스트 가이드](docs/testing-guide.md)의 전체 실행 절차를 따르세요.

```sh
python scripts/ai_smoke_test.py validation limit fallback
node --test tests/chat-api.test.mjs
```

스모크는 기존 여섯 사례를 직접 실행합니다. 인자 없이 실행하면 API 키가 있는 경우
실제 AI 호출도 포함하므로, 오프라인 검증에는 위처럼 사례를 지정합니다.
2026-09-25 검증 결과: 전용 MySQL·Chromium을 포함한 pytest 114개, JS 테스트 11개,
오프라인 AI 스모크 3개 시나리오가 통과했습니다. 실제 AI 호출 테스트 1개는 제외했으며,
외부 배포 환경은 이번 검증에 포함하지 않았습니다.
