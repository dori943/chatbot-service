# 채팅 통합: 스키마 반영과 검증

## 기존 DB 반영

먼저 DB를 백업하고 `SHOW TABLES`, `SHOW CREATE TABLE login`,
`SHOW CREATE TABLE chat_logs`로 실제 구조를 확인합니다.
초기화가 실패했던 볼륨은 `login`만 존재할 수도 있습니다.

- `chat_logs`가 없고 `chatlog`도 없다면 수정된 `data/init.sql`을 기존 DB에 적용합니다.
  `CREATE TABLE IF NOT EXISTS`이므로 기존 `login` 데이터는 유지됩니다.
- `chatlog`만 존재한다면 백업 후 `RENAME TABLE chatlog TO chat_logs`로 이름을 맞춥니다.
- 두 테이블이 모두 있다면 어느 쪽에 데이터가 있는지 확인하고 병합 계획을 세웁니다. 자동으로 덮어쓰지 않습니다.

기존 `chat_logs`의 길이를 확인합니다.

```sql
SELECT MAX(CHAR_LENGTH(question)) AS max_question,
       MAX(CHAR_LENGTH(answer)) AS max_answer
FROM chat_logs;
```

5,000자를 넘는 데이터가 있으면 보존·이관 방식을 먼저 결정합니다.
초과 데이터가 없고 현재 구조가 기존 팀 스키마와 일치할 때 아래 변경을 적용할 수 있습니다.

```sql
ALTER TABLE chat_logs
    MODIFY id BIGINT NOT NULL AUTO_INCREMENT,
    MODIFY question VARCHAR(5000) NOT NULL,
    MODIFY answer VARCHAR(5000) NULL,
    MODIFY created_at DATETIME(6) NOT NULL;
```

`login.id`와 `chat_logs.user_id`가 모두 `VARCHAR(50)`인지도 확인합니다.
모델의 ID에 있는 SQLite 타입 변형은 자동 테스트용이며 MySQL에는 `BIGINT`로 생성됩니다.

개발 DB의 `docker compose down -v`는 데이터를 삭제하므로 이 절차에서는 사용하지 않습니다.

## MySQL 통합 테스트 (PowerShell)

기존 개발 컨테이너와 다른 이름·포트로 일회용 DB를 생성합니다.
아래 비밀번호는 로컬 테스트 전용이며 실제 서비스 설정에 사용하지 않습니다.
13307 포트가 사용 중이면 다른 빈 포트로 변경합니다.

```powershell
docker run -d --name chatbot-integration-test-db `
  -e MYSQL_ROOT_PASSWORD=integration-test-only `
  -e MYSQL_DATABASE=chatbot_integration_test `
  --mount "type=bind,source=$((Resolve-Path data/init.sql).Path),target=/docker-entrypoint-initdb.d/init.sql,readonly" `
  --tmpfs /var/lib/mysql -p 127.0.0.1:13307:3306 mysql:8.0 `
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci

docker logs --tail 30 chatbot-integration-test-db
```

로그에서 최종 서버의 `ready for connections`를 확인한 뒤 실행합니다.

```powershell
$env:MYSQL_TEST_URL='mysql+pymysql://root:integration-test-only@127.0.0.1:13307/chatbot_integration_test?charset=utf8mb4'
python -m pytest tests/test_mysql_integration.py -q
```

SQL/ORM 컬럼 정합성, 한글·이모지 5,000자 저장, 5,001자 초과 거부,
실제 회원가입·로그인·AI 모의 응답 저장·기록 조회를 검증합니다.
테스트 사용자와 기록은 이 테스트 DB에만 추가됩니다.

## 실제 AI 호출 (선택)

위 테스트 DB가 켜진 상태에서 `.env`의 `AI_API_KEY` 및 모델 설정을 사용합니다.
이 테스트는 실제 API를 호출하므로 사용량이 발생합니다. 실패·폴백에 따라 호출 수가 늘 수 있습니다.

```powershell
$env:RUN_LIVE_AI='1'
python -c "from dotenv import load_dotenv; load_dotenv(); import pytest; raise SystemExit(pytest.main(['tests/test_mysql_integration.py', '-q']))"
Remove-Item Env:RUN_LIVE_AI
```

실제 AI 답변을 MySQL에 저장하고 조회 API에서 같은 답변이 반환되는지 확인합니다.

테스트를 마치면 이 테스트 전용 컨테이너를 제거합니다. 내부 임시 데이터는 함께 사라집니다.

```powershell
docker rm -f chatbot-integration-test-db
Remove-Item Env:MYSQL_TEST_URL
```

## 브라우저 테스트 (선택)

```powershell
python -m playwright install chromium
$env:RUN_BROWSER_TESTS='1'
python -m pytest tests/test_browser_integration.py -q
Remove-Item Env:RUN_BROWSER_TESTS
```

별도 로컬 서버와 메모리 DB를 사용합니다. AI 응답은 모의 처리합니다.
게스트 전송 차단 → 한글 ID 로그인 → Bearer 헤더 전송 → 답변 표시·DB 저장 → 로그아웃 시 대화 분리를 확인합니다.

## 담당 영역별 변경

- 백엔드: 채팅 스키마, 인증 의존성, POST/GET API, 저장·오류 처리.
- 프론트: 토큰 전달, UTF-8 ID·만료 확인, 게스트 요청 안내, 계정 전환 중 이전 요청 결과 차단.
- AI: 기존 호출·폴백 로직 유지, 사용자 ID 타입을 문자열로 맞춤. 라우터에서 전체 호출 시간 상한 적용.
- 설정/테스트: `google-genai` 추가, 테스트 의존성 분리, AI 테스트의 경계값과 실패 종료 코드 보완.

팀 리뷰에서는 입력 한도를 최종 1,000자로 줄일지, 답변 초과 정책을 유지할지 확인합니다.
대화방별 문맥 관리 및 DB 기록의 화면 동기화는 별도 설계가 필요합니다.
