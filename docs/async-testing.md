# 비동기 DB 전환 검증

현재 리팩토링 브랜치의 인증·채팅 DB 처리는 `AsyncSession`과 `aiomysql`을 사용한다.
비밀번호 해싱·비교는 같은 요청에서 스레드풀로 실행하고 완료를 기다린다.
인증 및 문맥 조회 트랜잭션은 AI 호출 전에 종료한다.

채팅 성공 응답은 `{answer, request_id, created_at}`이며 `created_at`은 저장 시각의 UTC 값이다.
기록 조회는 최신순 배열을 반환하고 페이지네이션은 사용하지 않는다.
프론트 대화 목록은 여전히 `localStorage`를 사용하며 기록 조회 API와 연결되어 있지 않다.
시간 설정 이름은 `AI_TIMEOUT_SECONDS`, `AI_TOTAL_TIMEOUT_SECONDS`로 통일한다.

## 테스트 실행 (PowerShell)

프로젝트 가상환경에 `requirements-dev.txt`를 설치한 뒤 실행한다.
개발 Compose와 별도 프로젝트이며 테스트 MySQL 데이터는 임시 파일시스템에만 저장한다.
테스트 fixture는 **`chatbot_integration_test`의 `login`, `chat_logs` 데이터를 매번 비운다.**
개발 데이터를 테스트 DB로 복사하지 않는다.

```powershell
docker compose -p chatbot-async-test -f docker-compose.test.yml up -d --wait db-test
$env:MYSQL_TEST_URL='mysql+pymysql://root:integration-test-only@127.0.0.1:13307/chatbot_integration_test?charset=utf8mb4'
.\.venv\Scripts\python.exe -m pytest tests/test_auth_dependency.py tests/test_async_chat.py -q
docker compose -p chatbot-async-test -f docker-compose.test.yml down
Remove-Item Env:MYSQL_TEST_URL
```

애플리케이션 요청에는 비동기 MySQL 연결을 주입한다. 테스트 데이터 준비·확인은 동기 연결로 수행한다.
AI 응답은 모의 함수로 교체하므로 실제 AI 호출은 하지 않는다.

확인 범위:

- 토큰 서명·만료·사용자 존재 여부, 인증 설정·DB 오류 응답.
- 실제 MySQL 회원가입·로그인·채팅 저장·전체 기록 조회.
- 성공 응답의 `created_at`과 DB 저장 시각 일치.
- 최근 성공 대화의 문맥 전달.
- AI 대기 중 DB 트랜잭션 종료 및 다른 요청 처리.
- 비밀번호 계산 대기 중 다른 요청 처리.
- 문맥 조회 실패 후 트랜잭션 복구 및 저장 가능 여부.
- 타임아웃 환경 변수 이름 반영.

이 테스트 범위는 19개다. 기존 채팅·브라우저·AI 스모크 테스트에는 예전 모듈 경로 및 API 계약이 남아 있다.
전체 테스트 이관, 채팅 오류 응답·입력 검증·로깅 정리는 후속 작업이다.

비동기 드라이버 의존성이 추가되었으므로 개발 서버에 반영할 때는 backend 이미지를 다시 빌드한다.

```powershell
docker compose up -d --build backend
```
