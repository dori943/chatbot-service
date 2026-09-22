# chatbot-service (작성중)

FastAPI에서 화면과 API를 함께 제공하는 AI 챗봇입니다.

## 실행

1. `.env.example`을 참고해 `.env`를 준비합니다. 기존 `.env`는 덮어쓰지 않습니다.
2. MySQL 설정, `SECRET_KEY`, `AI_API_KEY`를 입력합니다. 키는 Git에 올리지 않습니다.
3. 기존 DB 볼륨이 있다면 아래 스키마 안내를 먼저 확인합니다.
4. 프로젝트 루트에서 실행합니다.

```sh
docker compose up --build -d
docker compose ps
docker compose logs --tail 50 backend
```

화면: http://127.0.0.1:8000 / API 문서: http://127.0.0.1:8000/docs

회원가입 후 로그인하고 질문을 전송합니다. 화면과 API가 같은 서버에 있으므로
별도의 프론트 서버 없이 동작합니다.

## API

| 메서드 | 경로 | 동작 | 인증 |
|---|---|---|---|
| POST | `/auth/register` | `{ "id": "...", "pw": "..." }` 회원가입 | 없음 |
| POST | `/auth/login` | 같은 형식으로 로그인, 성공 시 `token` 반환 | 없음 |
| POST | `/api/chat` | 질문 전송, AI 응답 및 성공·실패 기록 저장 | Bearer 토큰 |
| GET | `/api/me/chats?limit=50&offset=0` | 본인 기록 조회, 최신순 | Bearer 토큰 |

채팅 요청 헤더: `Authorization: Bearer <로그인 응답의 token>`

요청:

```json
{ "question": "FastAPI가 뭐야?" }
```

성공 응답 (`200`):

```json
{
  "answer": "FastAPI는 파이썬으로 API를 만드는 프레임워크입니다.",
  "request_id": "요청별 식별자",
  "created_at": "2026-09-22T07:00:00Z"
}
```

기록 응답은 `{ "items": [...], "total": 0 }` 형식이며 각 항목은
`id`, `question`, `answer`, `status`, `created_at`을 포함합니다.
`total`은 본인의 전체 기록 수입니다. `limit`은 1~100, `offset`은 0 이상입니다.
사용자 ID는 요청 본문이 아닌 검증된 로그인 토큰에서 가져옵니다.

오류는 `{ "error_code": "...", "message": "한국어 안내", "request_id": null }` 형식입니다.
AI 호출 후 오류에는 요청 식별자가 포함됩니다.

| 상태 | 대표 오류 |
|---|---|
| 401 | `UNAUTHORIZED`: 토큰 누락·만료·위조, 존재하지 않는 사용자 |
| 422 | `INVALID_INPUT`: 요청 검증 실패 / `AI_BLOCKED`: AI 안전 필터 차단 |
| 429 | `AI_RATE_LIMIT`: AI 요청 제한 |
| 502 | AI 연결·응답 오류, `AI_ANSWER_TOO_LONG` 등 |
| 503 | `DB_UNAVAILABLE`: DB 조회·저장 실패 / `AUTH_UNAVAILABLE`: 인증 설정 누락 |
| 504 | `AI_TIMEOUT`: AI 응답 시간 초과 |

## 데이터 및 현재 범위

- SQL과 ORM의 테이블 이름은 `chat_logs`, 질문·답변은 모두 `VARCHAR(5000)`입니다.
- 질문은 필수, 실패한 AI 답변은 `NULL`입니다. 생성 시각은 DB에 UTC로 저장하고 API에서는 `Z`로 반환합니다.
- 프론트·요청 스키마의 질문 한도는 5,000자입니다. `MAX_QUESTION_LENGTH`를 더 작게 설정하면 AI 호출 전 해당 한도도 적용됩니다.
- AI 답변이 5,000자를 넘으면 자르지 않고 `AI_ANSWER_TOO_LONG` 실패 기록을 저장합니다.
- 입력·인증 검증 실패는 AI를 호출하지 않으며 채팅 기록을 만들지 않습니다.
- DB 저장 실패는 503으로 알립니다. 이때 AI 답변은 생성됐더라도 기록이 저장되지 않을 수 있습니다.
- 이번 API는 질문별 응답입니다. 대화방 ID가 없어 이전 기록을 AI 문맥으로 자동 연결하지 않습니다.
- 화면의 대화 목록·삭제는 기존 브라우저 저장소 동작을 유지합니다. DB 기록 조회는 `/api/me/chats`에서 제공하며 화면 동기화·서버 삭제는 후속 작업입니다.
- 화면의 중지 버튼은 응답 대기를 취소합니다. 이미 시작된 서버 처리·기록 저장까지 취소됨을 보장하지 않습니다.

`init.sql`은 빈 MySQL 데이터 디렉터리에서 최초 한 번만 실행됩니다.
기존 볼륨에는 소스 변경이 자동 적용되지 않습니다.
[기존 DB 반영 및 검증 방법](docs/chat-integration.md)을 확인하세요.

## 테스트

가상환경의 Python에서 실행합니다. 기본 테스트는 실제 AI나 개발 DB를 사용하지 않습니다.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
node --test tests/chat-api.test.mjs
python scripts/ai_smoke_test.py validation limit fallback
```

MySQL·브라우저·실제 Gemini 호출 검증은 [통합 테스트 안내](docs/chat-integration.md)를 참고하세요.
