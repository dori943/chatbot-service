# 팀원용 테스트 가이드

| 항목 | 내용 |
|---|---|
| 작성자 | 이건탁 |
| 최초 작성일 | 2026-09-22 |
| 최종 수정일 | 2026-09-22 |
| 버전 | v1.0.0 |
| 대상 브랜치 | feat/lgt-back/chat-integration |

> 문서를 고칠 때는 최종 수정일과 버전을 함께 갱신합니다. 변경 이력은 문서 맨 아래 변경 이력을 참고하세요.

채팅 통합 브랜치를 각자 로컬에서 검증하는 방법입니다.
처음이면 **1 → 2 → 3** 순서만 따라도 충분합니다.
고급 통합 검증(실 MySQL/실 Gemini/브라우저 자동화)은 [chat-integration.md](chat-integration.md)를 참고하세요.

---

## 0. 사전 준비

- Docker Desktop, Python 3.11+, Node 18+ 설치
- 저장소 루트에서 작업합니다. 예: `C:\dev\7-2\chatbot-service`
- `.env.example`을 복사해 `.env`를 만들고 값을 채웁니다. **`.env`는 커밋 금지입니다.**

```powershell
Copy-Item .env.example .env   # 이미 있으면 건너뜁니다(덮어쓰지 마세요)
```

필요한 값: MySQL 설정(`MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`),
`SECRET_KEY`, `AI_API_KEY`. 키 값은 팀 채널에서 공유하고 Git에는 올리지 않습니다.

---

## 1. 자동 테스트 (실제 AI·DB 사용 안 함, 빠르고 안전)

가상환경에서 실행합니다. 이 단계는 Docker 없이도 됩니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

.\.venv\Scripts\python.exe -m pytest tests -q
node --test tests/chat-api.test.mjs
.\.venv\Scripts\python.exe scripts/ai_smoke_test.py validation limit fallback
```

기대 결과:

- `pytest`: **37 passed, 5 skipped** (skip은 환경변수 필요한 통합 테스트라 정상)
- `node --test`: **11 pass / 0 fail**
- `ai_smoke_test`: 입력검증·컨텍스트·폴백 **모두 PASS**

> macOS/Linux는 `.\.venv\Scripts\python.exe` 대신 `.venv/bin/python`을 사용합니다.

---

## 2. 수동 테스트 (실제 서버 + DB 띄우기)

`app/db.py`가 DB 호스트를 `db`로 사용하므로 **로컬 단독 실행이 아니라 docker compose로** 띄웁니다.

### 2-1. 컨테이너 실행

```powershell
docker compose up --build -d
docker compose ps
```

`chatbot-db`가 `healthy`, `chatbot-backend`가 `Up` 이면 준비 완료입니다.
(DB 헬스체크 통과까지 10~20초 걸릴 수 있습니다.)

### 2-2. 초기화 로그 확인

```powershell
docker compose logs db | Select-String -Pattern "init.sql|ERROR|ready for connections"
docker compose logs backend --tail 30
```

`ERROR 1064` 같은 SQL 오류가 없어야 합니다. 있으면 아래 4번 문제해결을 보세요.

### 2-3. 브라우저에서 확인

- 화면: <http://127.0.0.1:8000>
- API 문서(Swagger): <http://127.0.0.1:8000/docs>

확인 흐름:

1. **회원가입** — 새 아이디로 가입합니다. (이미 쓴 아이디는 중복 오류가 납니다. 4번 참고)
2. **로그인** — 로그인하면 상단에 사용자 ID가 표시됩니다.
3. **질문 전송** — 답변이 표시되고, 로그인한 사용자에게만 본인 기록이 보입니다.
4. **로그아웃** — 대화가 분리되는지 확인합니다.

### 2-4. 저장된 기록 직접 확인 (선택)

`<root_pw>`는 `.env`의 `MYSQL_ROOT_PASSWORD` 값으로 바꿉니다.

```powershell
docker exec chatbot-db mysql -uroot -p"<root_pw>" -e "USE chatbot_db; SHOW TABLES; SELECT id FROM login; SELECT id, user_id, status, LEFT(question,20) FROM chat_logs ORDER BY id DESC LIMIT 5;"
```

`login`, `chat_logs` 테이블과 방금 만든 계정·기록이 보이면 정상입니다.

---

## 3. 정리

```powershell
docker compose down          # 컨테이너만 정지 (DB 데이터 유지)
docker compose down -v       # DB 볼륨까지 삭제 (완전 초기화, 데이터 사라짐 주의)
```

---

## 4. 자주 나오는 문제

### 회원가입 시 "서버 연결에 실패했습니다"

대부분 **연결 문제가 아니라 이미 존재하는 아이디**입니다.
현재 회원가입은 중복 아이디를 곱게 처리하지 못해 500이 나고, 화면은 이를 위 메시지로 표시합니다.

- 해결: **새 아이디로 가입**하거나 **기존 아이디로 로그인**하세요.
- 확실히 하려면 `docker compose logs backend --tail 20`에서
  `Duplicate entry ... for key 'login.PRIMARY'`를 확인합니다.

### DB가 바로 죽음 / `chatbot-db` `Exited (1)`

`init.sql` 문법 오류로 초기화에 실패하면 컨테이너가 종료됩니다.
MySQL은 데이터 디렉터리가 비어있지 않으면 `init.sql`을 다시 실행하지 않으므로,
초기화가 한 번 실패한 볼륨은 그냥 재시작해도 테이블이 생기지 않습니다.

- 해결: 남길 데이터가 없다면 완전 초기화합니다.

```powershell
docker compose down -v
docker compose up --build -d
```

- 남길 데이터가 있으면 지우지 말고 [chat-integration.md](chat-integration.md)의 기존 DB 반영 절차를 따르세요.

### backend가 재시작 반복 / 모듈 없음(`No module named ...`)

오래된 이미지일 수 있습니다. `--build`로 다시 빌드하세요.

```powershell
docker compose up --build -d
```

### 채팅은 되는데 AI 오류가 남

`.env`의 `AI_API_KEY`와 모델 설정을 확인합니다. 오류 코드별 의미는 [README](../README.md)의 오류 표를 참고하세요.

---

## 다음 단계

실 MySQL 정합성, 실제 Gemini 호출, 브라우저 자동화(Playwright)까지 검증하려면
[chat-integration.md](chat-integration.md)를 참고하세요.

---

## 변경 이력

| 버전 | 날짜 | 작성자 | 내용 |
|---|---|---|---|
| v1.0.0 | 2026-09-22 | 이건탁 | 최초 작성. 자동 테스트·수동 브라우저 테스트·문제해결 정리 |
