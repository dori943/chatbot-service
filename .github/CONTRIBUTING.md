# 협업 컨벤션 (Contributing Guide)

> [Codyssey] 웹 기반 AI 챗봇 서비스 — 팀 개발 규칙
> 모든 팀원은 작업 시작 전 이 문서를 읽고 따릅니다.

---

## 1. 팀 역할

| 역할 | 담당자 | 주요 책임 | 주 작업 디렉터리 |
|---|---|---|---|
| 프론트엔드 | 채민성 | 로그인/회원가입/채팅 UI, 에러 UX, 로그 조회 화면 | `templates/`, `static/` |
| 백엔드 | 방승규, 이건탁 | 인증·접근제어, DB 모델/조회 API, 로깅, 배포 | `app/routers/`, `app/models/`, `app/core/` |
| AI 연동 | 김도희 | AI API 호출, 컨텍스트 구성, 타임아웃/예외 처리 | `app/services/ai_service.py` |

> ⚠️ 원칙: **다른 사람의 담당 디렉터리를 말없이 수정하지 않습니다.** 필요하면 이슈나 PR 코멘트로 요청합니다.

---

## 2. 브랜치 전략

```
main          배포 가능한 안정 버전. 직접 push 금지. develop에서만 PR로 병합.
 └ develop    통합 개발 브랜치. 기본 작업 기준점. 직접 push 금지.
    ├ feat/dohee-ai/login-api
    ├ feat/sg-backend/chat-ui
```

### 브랜치 이름 규칙

```
<타입>/<이름-역할>/<간단한-영문-설명>
```

| 타입 | 용도 | 예시 |
|---|---|---|
| `feat` | 새 기능 | `feat/js-frontend/chat-ui`, `feat/dh-ai/user-auth` |
| `fix` | 버그 수정 | `fix/sg-backend/session-expire` |
| `refactor` | 리팩터링 (동작 변화 없음) | `refactor/dh-ai/ai-service` |
| `docs` | 문서 | `docs/dh-ai/api-spec` |
| `chore` | 설정·패키지·빌드 | `chore/dh-ai/gitignore` |

- 소문자 + 하이픈(`-`)만 사용. 한글·공백·언더스코어 금지.
- 브랜치는 **기능 하나 단위**로 작게. 작업이 끝나면 병합 후 삭제.

### 작업 흐름

```bash
git checkout develop
git pull origin develop          # 항상 최신화 후 시작
git checkout -b feat/dh-ai/chat-ui
# ... 작업 & 커밋 ...
git push -u origin feat/dh-ai/chat-ui
# GitHub에서 develop ← feat/chat-ui 로 PR 생성
```

---

## 3. 커밋 메시지 컨벤션

**타입은 영어, 내용은 한글**로 작성합니다.

```
<타입>: <무엇을 했는지 한 줄 요약>

(선택) 본문 — 왜 이렇게 했는지, 참고사항
(선택) 관련 이슈: #12
```

### 타입 목록

| 타입 | 의미 |
|---|---|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 코드 구조 개선 (기능 변화 없음) |
| `style` | 포맷팅, 세미콜론 등 (로직 변화 없음) |
| `docs` | 문서 수정 |
| `test` | 테스트 코드 |
| `chore` | 패키지, 설정 파일, 기타 잡무 |

### 좋은 예 ✅

```
feat: 로그인 API 및 세션 발급 구현
fix: AI 응답 타임아웃 시 500 에러 나던 문제 수정
refactor: AI 호출 로직을 ai_service로 분리
docs: README에 환경 변수 설정 방법 추가
chore: .env를 .gitignore에 추가
```

### 나쁜 예 ❌

```
수정                      ← 무엇을 수정했는지 알 수 없음
feat: 여러가지 작업        ← 한 커밋에 너무 많은 일
Update main.py            ← 파일명만으로는 의도를 알 수 없음
ㅁㄴㅇㄹ                   ← 의미 없는 커밋
```

### 커밋 규칙

- **작게, 자주.** 기능 하나가 동작하는 단위마다 커밋합니다.
- 팀원별 **유의미한 커밋 10회 이상**이 평가 요구사항입니다. 막판에 몰아서 하지 마세요.
- `.env`, `*.db`, `__pycache__` 등은 **절대 커밋 금지** (아래 `.gitignore` 참고).
- 커밋 전 서버가 정상 실행되는지 확인합니다.

---

## 4. Pull Request 규칙

### 기본 원칙

- **`main`, `develop`에 직접 push 금지.** 모든 병합은 PR을 통해서만.
- PR 제목은 커밋 컨벤션과 동일한 형식: `feat: 로그인 API 구현`
- PR 본문은 `.github/PULL_REQUEST_TEMPLATE.md` 양식을 채웁니다.
- **최소 1명의 승인(Approve)** 후 병합합니다.
- 병합 방식은 **Squash and merge** 권장 (히스토리가 깔끔해집니다).
- 병합 후 작업 브랜치는 삭제합니다.

### 리뷰 규칙

- 리뷰는 **24시간 내** 응답합니다. (급하면 팀 채팅으로 알림)
- 리뷰 코멘트는 근거를 함께 적습니다. "이건 아닌 것 같아요" ❌ → "여기서 `.env` 값을 직접 참조하면 배포 환경에서 None이 될 수 있어요" ✅
- 사소한 제안은 `nit:` 접두사를 붙여 부담을 줄입니다.
- 본인 PR은 본인이 승인할 수 없습니다.

### PR 크기

- 변경 파일 10개 / 300줄 이내를 목표로 합니다. 그보다 커지면 쪼개세요.

---

## 5. 이슈 관리

- 기능·버그는 이슈로 먼저 등록하고, 브랜치를 그 이슈에 연결합니다.
- PR 본문에 `Closes #12` 를 쓰면 병합 시 이슈가 자동으로 닫힙니다.

### 라벨

| 라벨 | 용도 |
|---|---|
| `frontend` / `backend` / `ai` | 담당 영역 |
| `feat` / `bug` / `docs` | 작업 유형 |
| `priority: high` | 우선 처리 |
| `blocked` | 다른 작업이 끝나야 진행 가능 |

---

## 6. 프로젝트 구조

```
.
├── app/
│   ├── main.py                 # FastAPI 엔트리포인트
│   ├── core/
│   │   ├── config.py           # 환경 변수 로드
│   │   ├── security.py         # 비밀번호 해싱, 세션/토큰
│   │   └── logging.py          # 로깅 설정
│   ├── models/                 # SQLAlchemy 모델 (User, ChatLog)
│   ├── schemas/                # Pydantic 요청/응답 스키마
│   ├── routers/
│   │   ├── auth.py             # 회원가입 / 로그인 / 로그아웃
│   │   └── chat.py             # /api/chat, /api/me/chats
│   ├── services/
│   │   └── ai_service.py       # AI API 호출 · 컨텍스트 구성 · 타임아웃
│   └── db.py                   # DB 세션
├── templates/                  # Jinja2 템플릿
├── static/                     # CSS / JS
├── scripts/
│   └── check_logs.sql          # 평가용 대화 로그 확인 쿼리
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── ISSUE_TEMPLATE/
├── data/                    # DB 내용
├── docker-compose.yml       
├── Dockerfile               
├── .dockerignore           
├── .env.example
├── .gitignore
├── requirements.txt
├── CONTRIBUTING.md
└── README.md
```

## 6. 환경 변수 & 보안

- 모든 민감정보는 `.env`로 관리하고, **저장소에 올리지 않습니다.**
- 키를 추가했다면 반드시 `.env.example`에 **이름만** 추가하고 커밋합니다.
- 실수로 `.env`를 커밋했다면 즉시 팀에 알리고 **키를 재발급**합니다. (히스토리에 남으므로 삭제 커밋만으로는 불충분)

