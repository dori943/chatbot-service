# 챗봇 서비스 코드 분석 및 학습 요약 (v1.2)

본 문서는 `c:\dev\7-2\chatbot-service` 프로젝트의 전체적인 아키텍처와 프론트엔드-백엔드 통신 흐름, 그리고 백엔드 핵심 비즈니스 로직(파이프라인, AI 연동, DB 영속화)을 분석한 내용을 체계적으로 정리한 문서입니다.

---

## 1. 코드 탐색 경로 (Trace Path)
사용자가 브라우저에서 화면을 보고 채팅을 전송하는 시점부터, 백엔드가 이를 처리하여 결과를 반환하기까지의 논리적인 흐름을 따라 코드를 분석했습니다.

### 1단계: 백엔드 엔트리포인트 및 프론트엔드 서빙 (`app/main.py`)
- FastAPI 인스턴스 생성 및 수명 주기(Lifespan) 관리.
- 전역 미들웨어(로깅) 및 유형별 전역 예외 처리기(Exception Handler) 등록.
- `Jinja2Templates`를 활용한 SSR(Server-Side Rendering) 설정으로 별도의 React/Node.js 서버 없이 백엔드 단일 서버에서 `templates/index.html` 서빙.

### 2단계: 프론트엔드 UI 화면 (`templates/index.html`)
- 채팅 입력을 위한 `<form id="chat-form">`, `<textarea id="question">`, 전송 버튼 렌더링.
- JavaScript가 DOM 이벤트를 바인딩할 수 있도록 요소별 고유 식별자(`id`) 제공.
- 상단 `<script type="module" src="/static/js/chat.js">`를 통해 클라이언트 로직 모듈 로드.

### 3단계: 프론트엔드 이벤트 제어 및 통신 (`static/js/chat.js` & `chat-api.js`)
- **이벤트 바인딩 (`bindChatEvents`)**: DOM의 `#chat-form` 제출(submit) 및 Enter 키 입력 이벤트를 감지하여 핸들러로 위임.
- **기본 동작 방지 (`handleSubmit`)**: 브라우저의 기본 페이지 새로고침 동작을 `event.preventDefault()`로 가로채어(Intercept) 싱글 페이지 방식의 비동기 통신으로 전환.
- **백엔드 API 호출 (`requestReply`)**: Fetch API를 통해 백엔드의 `/api/chat` 엔드포인트로 JSON 데이터(`room_id`, `room_name`, `question`)와 인증 토큰을 POST 요청.

### 4단계: 백엔드 라우터 / Controller (`app/routers/chat.py`)
- `@router.post("/chat")`: 프론트엔드의 요청을 수신하는 비동기(`async def`) 핸들러.
- **입력 검증**: Pydantic 스키마(`ChatRequest`)를 통해 요청 본문(Body)의 데이터 규격 자동 검증 (미충족 시 422 에러 즉시 반환).
- **의존성 주입 (Dependency Injection)**:
  - `user_id = Depends(get_token_id)`: 토큰을 해독하여 현재 사용자 식별자 추출.
  - `db = Depends(get_db)`: 비동기 데이터베이스 세션(`AsyncSession`) 할당.
- **컨트롤러 역할**: 라우터 자체는 복잡한 로직을 수행하지 않고, 준비된 객체들을 Service 레이어(`chat_main.chat`)로 위임.
- **조회 엔드포인트 (`@router.get("/me/chats")`)**: RESTful API 관례에 따라 인증된 현재 사용자('me')의 전체 대화 이력 조회 처리.

### 5단계: 백엔드 핵심 비즈니스 파이프라인 (`app/services/chat_main.py`)
`chat()` 함수는 8단계의 엄격한 순차적 파이프라인으로 동작합니다:
1. **2차 비즈니스 검증**: `validate_room_id`, `validate_room_name`, `validate_question`을 통한 공백(`.strip()`) 및 최대 길이 초과 검증.
2. **요청 추적 식별자 할당**: 분산 환경 및 로그 분석을 위한 고유 UUID(`request_id`) 부여.
3. **대화 문맥(Context) 로드**: AI가 이전 대화를 기억할 수 있도록 DB에서 과거 이력 조회 (`chat_db.get_history`).
4. **레이턴시 측정**: AI 응답 소요 시간 측정을 위한 타이머 시작 (`time.perf_counter()`).
5. **AI 호출 및 타임아웃 방어막**: `asyncio.wait_for(AI_connect.generate_answer(...), timeout=...)`를 통해 외부 AI의 무응답으로 인한 서버 멈춤 방지.
6. **장애 가로채기 및 Fallback 조립**: 타임아웃 또는 예외 발생 시 서버가 죽지 않고 `AIResult(status="timeout" | "error")` 대체 객체 수동 생성.
7. **무조건적인 DB 영속화**: 성공/실패 여부와 상관없이 사용자의 질문과 처리 결과를 DB 테이블에 저장 (`chat_db.save_result`).
8. **응답 분기 및 반환**: 실패 시 정의된 `APIError` 예외 발생(전역 핸들러에서 502/504 반환), 성공 시 ISO-8601 UTC 시각을 포함한 최종 JSON 딕셔너리 반환.

### 6단계: 외부 AI 통신 및 결과 생성 (`app/services/AI_connect.py`)
- **함수 연동 메커니즘**: `chat_main.py`의 `AI_connect.generate_answer(...)` 호출은 `AI_connect.py`의 `async def generate_answer(...) -> AIResult`로 연결되며, 리턴값이 `chat_main.py`의 `result` 변수로 전달됨.
- **`status="success"`의 기원**: 외부 LLM(Gemini 등) 모델과의 통신이 성공하여 정상 텍스트 답변이 생성되었을 때, `AI_connect.py` 285번째 줄에서 `AIResult(status="success", ...)` 객체가 최초 생성되어 반환됨.
- **재시도 및 모델 폴백**: 주 모델 호출 실패 시 재시도(`AI_MAX_RETRIES`) 및 백업 폴백 모델(`AI_FALLBACK_MODEL`)로 자동 전환하는 안전장치 구비.

### 7단계: 데이터베이스 영속화 계층 (`app/services/chat_db.py`)
SQLAlchemy 비동기 세션(`AsyncSession`)을 활용하여 채팅 데이터의 영속성(Persistence)과 트랜잭션을 전담합니다:
1. **`save_result` (대화 저장 - INSERT)**:
   - `ChatLog` ORM 엔티티를 생성하여 질문, 답변, 상태, 레이턴시, 모델명 등을 매핑.
   - `db.add()` 후 `await db.commit()`으로 즉시 영구 반영하며, 실패 시 `await db.rollback()` 후 503 에러 전파.
2. **`get_history` (문맥용 과거 대화 조회 - SELECT)**:
   - AI 문맥 오염을 방지하기 위해 `status == 'success'`인 정상 대화 건만 엄격히 필터링.
   - 최근 N개(`limit`)를 역순 조회(`order_by(ChatLog.id.desc())`) 후 시간순(`reversed`)으로 재배열하여 주입.
   - DB 에러 발생 시에도 전체 대화가 멈추지 않도록 빈 리스트(`[]`)를 반환하는 장애 격리(Fault Tolerance) 구현.
3. **`get_list_chat` (내 전체 대화 목록 조회 - SELECT)**:
   - 현재 사용자의 전체 대화 기록을 최신순으로 조회하여 반환.

---

## 2. 아키텍처 핵심 인사이트
1. **단일 서버 아키텍처**:
   - `Jinja2`를 활용하여 파이썬 단일 서버 내에서 프론트엔드 정적 리소스 서빙과 백엔드 REST API를 모두 처리하여 배포 및 인프라 복잡도를 최소화.
2. **관심사의 완벽한 분리 (Separation of Concerns)**:
   - **Presentation/Router (`app/routers`)**: HTTP 요청 수신, DTO 검증, 의존성 주입.
   - **Service/Orchestration (`app/services/chat_main.py`)**: 비즈니스 흐름 제어, 타임아웃 제어, 트랜잭션 조율.
   - **External Integration (`app/services/AI_connect.py`)**: LLM 연동, 토큰/프롬프트 빌딩, 재시도/폴백.
   - **Persistence (`app/services/chat_db.py`)**: 데이터베이스 쿼리 및 데이터 영속화.
3. **장애 격리 및 고가용성 (Fault Tolerance)**:
   - 외부 AI 서비스 지연에 대비한 `asyncio.wait_for` 기반 타임아웃 제어.
   - 문맥 조회 실패 시 빈 리스트 Fallback을 적용하여 단일 질문이라도 처리되도록 방어.
   - 에러 발생 시에도 비정상 종료(Crash)를 막고 Fallback 객체를 구성하여 DB에 실패 이력을 기록하는 감사(Audit) 추적성 확보.
4. **심층 방어 (Defense in Depth)**:
   - 입력값 검증: 라우터 1차(Pydantic 타입) ➔ 서비스 2차(비즈니스 공백/길이 제한).
   - 출력값 검증: 1차(isinstance 반환 타입) ➔ 2차(품질 검사 및 에러 강등).

---
*작업 브랜치: `docs/lgt-back/code-analysis`*  
*문서 버전: v1.2*
