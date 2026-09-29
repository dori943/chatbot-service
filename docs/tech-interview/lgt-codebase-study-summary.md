# 챗봇 서비스 코드 분석 및 학습 요약

본 문서는 `c:\dev\7-2\chatbot-service` 프로젝트의 전체적인 아키텍처와 프론트엔드-백엔드 통신 흐름을 분석한 내용을 요약한 문서입니다.

## 1. 코드 탐색 경로 (Trace Path)
사용자가 브라우저에서 화면을 보고 채팅을 전송하는 시점부터, 백엔드가 이를 처리하여 결과를 반환하기까지의 논리적인 흐름을 따라 코드를 분석했습니다.

1. **`app/main.py` (백엔드 엔트리포인트 및 프론트엔드 서빙)**
   - FastAPI 서버 설정, 에러 핸들러 및 미들웨어 등록.
   - `Jinja2Templates`를 사용해 SSR(Server-Side Rendering) 방식으로 별도의 React/Node.js 서버 없이 백엔드에서 직접 `index.html`을 서빙.
2. **`templates/index.html` (프론트엔드 UI)**
   - 채팅 화면 렌더링.
   - `<form id="chat-form">` 요소에 ID를 부여하여, 향후 JavaScript가 DOM 이벤트를 바인딩할 수 있도록 타겟을 제공.
3. **`static/js/chat.js` & `chat-api.js` (프론트엔드 로직)**
   - `bindChatEvents()`: HTML의 폼 제출(submit) 이벤트를 감지.
   - `handleSubmit()`: 브라우저 기본 동작인 새로고침을 `event.preventDefault()`로 방지(Intercept)하고 비동기 통신으로 전환.
   - `requestReply()`: Fetch API를 통해 백엔드의 `/api/chat` 엔드포인트로 JSON 데이터와 인증 토큰 전달.
4. **`app/routers/chat.py` (백엔드 라우터 / Controller)**
   - `@router.post("/chat")`에서 프론트엔드의 요청을 수신.
   - Pydantic(`ChatRequest`)으로 입력값을 검증하고, `Depends`를 통해 인증 토큰에서 유저 ID를 추출 및 DB 세션을 할당.
   - 실제 비즈니스 로직은 실행하지 않고 Service 레이어로 위임.
5. **`app/services/chat_main.py` (비즈니스 로직 / Service)**
   - 파라미터 유효성 재검증 및 DB(`chat_db.py`)에서 이전 채팅 이력 조회.
   - AI 모듈(`AI_connect.generate_answer`)을 호출하여 답변 생성 (Timeout 설정 적용).
   - 최종 결과를 DB에 저장한 후 Router로 응답 반환.

## 2. 아키텍처 핵심 인사이트
- **단일 서버 아키텍처**: 최신 SPA(Single Page Application) + 별도 API 서버 구조와 달리, `Jinja2`를 활용하여 파이썬 단일 서버 내에서 정적 파일 서빙과 API 처리를 모두 담당하도록 설계되어 복잡도를 낮추었습니다.
- **관심사의 분리 (Separation of Concerns)**:
  - **Router**: HTTP 요청/응답 형식 처리 및 의존성 주입(`app/routers`).
  - **Service**: 비즈니스 로직, AI 연동, DB 트랜잭션 관리(`app/services`).
  - **DOM & API**: 프론트엔드에서는 화면 갱신(`chat.js`)과 서버 통신(`chat-api.js`)을 별도 모듈로 분리.
- **안정성 (Robustness)**:
  - 전역 에러 핸들러를 통한 통합 예외 처리(`main.py`).
  - AI 응답 지연에 대비한 엄격한 Timeout 처리(`chat_main.py`).

---
*작업 브랜치: `docs/lgt-back/code-analysis`*
