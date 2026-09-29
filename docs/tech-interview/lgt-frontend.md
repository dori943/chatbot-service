# 프론트엔드 예상 구술 문답 12선

[전체 학습 안내](README.md) · [팀 역할 문서](../../.github/CONTRIBUTING.md)

팀 역할 문서에는 프론트엔드 담당자가 **채민성**, 담당 범위가 로그인·회원가입·채팅 UI와 오류 안내 등으로 적혀 있습니다. 아래 문답은 현재 로컬 코드의 프론트엔드 역할을 공부하기 위한 자료이며, 특정 개인이 각 기능을 작성했다는 Git 이력 검증은 아닙니다. 답변의 구현 설명과 개선 제안을 구분해서 말하세요. 연결한 테스트는 기존 검증 코드이며, 이 문서 작성 중 테스트를 실행하지는 않았습니다.

## F01. 화면이 열리고 질문의 답이 표시되기까지 프론트엔드는 무엇을 하나요?

**모범 답변:** “FastAPI의 `/`가 `index.html`을 반환하고, 화면에서 `auth.js`와 `chat.js` 모듈을 불러옵니다. 질문을 제출하면 `handleSubmit()`이 로그인과 입력을 확인하고, `requestReply()`가 서버의 `/api/chat`에 요청합니다. 성공한 답변은 대화 배열에 추가한 뒤 `renderChat()`으로 같은 화면에 표시하고 브라우저 저장소에도 저장합니다. AI API를 직접 부르는 것은 백엔드이고 프론트에는 AI API 키가 필요하지 않습니다.”

**꼬리 질문:** 화면 파일과 요청 함수를 왜 나눴나요?  
**답변:** “HTML은 화면 구조, `chat.js`는 화면 상태와 이벤트, `chat-api.js`는 HTTP 통신을 담당합니다. 통신 부분은 DOM 없이 별도로 검증할 수 있습니다.”

**코드 근거:** [main.py](../../app/main.py)의 `home()`, [index.html](../../templates/index.html)의 모듈 로딩, [chat.js](../../static/js/chat.js)의 `handleSubmit()`·`renderChat()`, [chat-api.js](../../static/js/chat-api.js)의 `requestReply()`.  
**검증 코드:** [chat-api.test.mjs](../../tests/chat-api.test.mjs)의 `로그인 토큰과 질문을 전송하고 답변을 반환한다`.

## F02. 회원가입과 로그인은 화면에서 어떻게 처리하나요?

**모범 답변:** “한 인증 모달에서 탭에 따라 회원가입과 로그인을 구분하고, 각각 `/auth/register`와 `/auth/login`에 `{id, pw}`를 POST합니다. 회원가입 때는 비밀번호 확인값이 같은지 먼저 검사하며, 성공했다고 자동 로그인하지는 않습니다. 로그인에 성공하면 응답의 `token`을 `localStorage`의 `access_token`에 저장하고 사용자 이름과 로그아웃 버튼을 표시합니다. 로그아웃은 현재 브라우저의 토큰을 지우고 화면 상태를 갱신하는 방식입니다.”

**꼬리 질문:** 로그아웃하면 이미 발급한 토큰도 서버에서 즉시 폐기되나요?  
**답변:** “현재 프론트는 서버 로그아웃 요청을 보내지 않습니다. 브라우저에서 토큰을 삭제하는 동작과 서버에서 토큰을 무효화하는 설계는 구분해야 합니다.”

**코드 근거:** [auth.js](../../static/js/auth.js)의 `bindAuthEvents()`·`clearAuth()`·`renderAuthUI()`, [index.html](../../templates/index.html)의 `auth-form`.  
**검증 코드:** [test_browser_integration.py](../../tests/test_browser_integration.py)의 `test_login_room_context_and_owner_switch()`는 로그인과 로그아웃 후 화면 상태를 확인합니다. 회원가입의 모든 경우를 이 테스트가 검증한다고 말하지는 마세요.

## F03. 프론트에서 로그인 여부를 검사하면 접근 제어가 완성되나요?

**모범 답변:** “프론트의 `getAuthenticatedId()`는 JWT payload에서 ID와 만료 시간을 읽어서 화면을 제어하지만, 서명을 검증하지는 않습니다. 실제 접근 제어는 백엔드가 Bearer 토큰의 서명·만료와 사용자 존재 여부를 확인해서 수행합니다. 브라우저 저장값이나 JavaScript를 바꿀 수 있으므로 프론트 검사만으로 권한을 보장하면 안 됩니다. 또한 `localStorage`에 저장한 토큰은 페이지의 JavaScript가 읽을 수 있어, 사용자 입력을 안전하게 표시하는 것도 중요합니다.”

**꼬리 질문:** 요청 본문에 사용자 ID를 넣어서 신뢰해도 되나요?  
**답변:** “현재 채팅 요청은 사용자 ID를 보내지 않고 Authorization 헤더의 토큰을 보냅니다. 서버가 검증한 토큰에서 사용자 ID를 얻는 구조입니다.”

**코드 근거:** [auth.js](../../static/js/auth.js)의 `getTokenClaims()`·`getAuthenticatedId()`, [chat-api.js](../../static/js/chat-api.js)의 Authorization 설정, [dependencies.py](../../app/core/dependencies.py)의 `get_token_id()`.  
**검증 코드:** [test_browser_integration.py](../../tests/test_browser_integration.py)의 `test_expiry_and_401_clear_token_and_login_ui()`.

## F04. 질문 입력은 어떻게 검증하고 키보드 입력은 어떻게 처리하나요?

**모범 답변:** “화면에는 `required`와 `maxlength="5000"`가 있고, 제출 함수에서도 앞뒤 공백을 없앤 뒤 빈 질문과 5,000자 초과를 검사합니다. Enter는 전송하고 Shift+Enter는 줄바꿈으로 남기며, 한글 조합 중 Enter가 바로 전송되지 않도록 `isComposing`도 확인합니다. 사용자에게 빠르게 안내하는 프론트 검사와 별개로, 서버도 질문을 다시 검사합니다. 서버 설정이 5,000자보다 작으면 서버가 더 짧은 제한을 적용하므로 화면과 설정의 일치 여부도 확인해야 합니다.”

**꼬리 질문:** 입력 검증을 프론트와 서버 양쪽에서 하는 이유는 무엇인가요?  
**답변:** “프론트 검사는 사용자가 즉시 수정하도록 돕습니다. 서버 검사는 화면을 거치지 않은 요청에도 같은 규칙을 적용합니다.”

**코드 근거:** [index.html](../../templates/index.html)의 `question`, [chat.js](../../static/js/chat.js)의 `handleSubmit()`·`bindChatEvents()`·`updateInput()`, [chat_main.py](../../app/services/chat_main.py)의 `validate_question()`.

**심화 포인트:** HTML의 `maxlength`와 JavaScript의 `Array.from(...).length`는 문자 길이를 세는 단위가 다를 수 있습니다. 이모지가 포함된 경계값에서는 화면 제한과 서버 제한이 정확히 일치한다고 단정하지 말고 별도로 확인해야 합니다.

## F05. 프론트와 백엔드가 맞춰야 하는 실제 API 계약은 무엇인가요?

**모범 답변:** “채팅은 `POST /api/chat`이고 JSON 본문에 `question`, `room_id`, `room_name` 세 필드를 보냅니다. 헤더에는 JSON 형식과 `Bearer` 토큰을 지정하며, 현재 서버 스키마에서 세 본문 필드는 모두 필수입니다. 서버 성공 응답에는 `answer`와 방 정보, 요청 ID, 생성 시각이 있고, 현재 프론트의 요청 함수는 그중 `answer`만 화면 코드에 반환합니다. `await fetch()`로 응답을 기다리되 성공 상태와 비어 있지 않은 답변 문자열인지도 따로 검사합니다.”

**꼬리 질문:** `fetch()`가 완료됐으면 401이나 500도 성공인가요?  
**답변:** “HTTP 응답을 받았다는 의미이므로 `response.ok`를 따로 봅니다. 오류 상태면 안내 문구와 상태코드를 담은 오류를 만들어 화면 처리로 넘깁니다.”

**요청 본문 예시:**

```json
{"question": "안녕", "room_id": "room-example", "room_name": "첫 대화"}
```

**코드 근거:** [chat-api.js](../../static/js/chat-api.js)의 `requestReply()`, [schemas/chat.py](../../app/schemas/chat.py)의 `ChatRequest`, [chat_main.py](../../app/services/chat_main.py)의 성공 응답.  
**검증 코드:** [chat-api.test.mjs](../../tests/chat-api.test.mjs)의 요청 본문·Authorization 검사, [test_browser_integration.py](../../tests/test_browser_integration.py)의 `send_question()` 내부 요청·응답 방 정보 검사.

## F06. 사용자가 전송을 연속으로 누르면 어떻게 되나요?

**모범 답변:** “채팅 요청 중에는 `pending`에 AbortController가 있고, 제출 함수의 첫 검사에서 추가 전송을 막습니다. `setBusy(true)`는 입력창과 방 전환·새 대화·삭제 동작을 잠그고 전송 버튼 대신 중지 버튼을 보여줍니다. 성공하면 답변을 추가하고 입력을 비우며, 실패하면 임시로 추가한 사용자 메시지를 되돌립니다. 일반 오류나 사용자 중지에서는 질문을 입력창에 남겨 다시 시도할 수 있게 합니다.”

**꼬리 질문:** 그러면 서비스 전체에서 중복 처리가 절대 일어나지 않나요?  
**답변:** “이 장치는 현재 화면의 채팅 중복 제출을 막습니다. 여러 탭에서 보내는 요청이나 재전송까지 막으려면 서버의 중복 요청 처리 설계가 추가로 필요하며, 인증 폼에도 같은 `pending` 장치가 구현된 것은 아닙니다.”

**코드 근거:** [chat.js](../../static/js/chat.js)의 `handleSubmit()`·`setBusy()`·`newChat()`, [auth.js](../../static/js/auth.js)의 인증 폼 제출 처리.  
**추가 확인 방법:** 브라우저 Network에서 느린 응답을 재현한 뒤 채팅 연속 제출 시 요청 수와 버튼 복구를 확인합니다. 이 문서에서는 해당 검증을 실행하지 않았습니다.

## F07. AI 오류와 로그인 오류를 사용자에게 어떻게 구분해 보여주나요?

**모범 답변:** “`requestReply()`는 서버가 보낸 오류 메시지를 우선 사용하고, 메시지를 읽을 수 없으면 HTTP 상태별 기본 안내를 사용합니다. 로그인 문제인 401은 토큰을 정리하지만, AI 설정 문제나 AI 응답 오류 같은 503·502만으로 로그아웃하지는 않습니다. JSON이 아닌 오류 응답, 비어 있는 성공 답변, 네트워크 오류도 각각 처리합니다. 화면은 오류를 상태 영역에 표시하며 `role="alert"`를 적용합니다.”

**꼬리 질문:** AI 설정 오류 때 다시 로그인하라고 하면 왜 부정확한가요?  
**답변:** “사용자 인증과 외부 AI 서비스 상태는 다른 문제입니다. 유효한 로그인은 유지하고 실제 오류 안내를 보여주는 것이 맞습니다.”

**코드 근거:** [chat-api.js](../../static/js/chat-api.js)의 오류 응답 처리, [chat.js](../../static/js/chat.js)의 `handleSubmit()`·`setStatus()`.  
**검증 코드:** [chat-api.test.mjs](../../tests/chat-api.test.mjs)의 HTTP 상태별·비JSON 응답 검사, [test_browser_integration.py](../../tests/test_browser_integration.py)의 `test_ai_setting_errors_keep_login_and_save_failure()`.

## F08. 중지 버튼과 30초 시간 제한은 서버의 AI 작업까지 취소하나요?

**모범 답변:** “중지 버튼은 AbortController로 브라우저의 요청 대기를 취소하며, 채팅 HTTP 요청에는 별도로 30초 타이머도 있습니다. 사용자가 중지한 경우와 시간이 초과된 경우의 안내 문구는 구분합니다. 하지만 브라우저의 취소만으로 서버의 AI 호출이나 DB 저장까지 취소됐다고 보장할 수는 없습니다. 서버가 이미 처리한 요청을 다시 보내면 중복 대화가 생길 수 있으므로, 서버 취소나 중복 처리 방지는 별도의 개선 과제입니다.”

**꼬리 질문:** 30초 제한은 회원가입·로그인 요청에도 적용되나요?  
**답변:** “현재 그 타이머는 `chat-api.js`의 채팅 요청에만 있습니다. 인증 요청은 `auth.js`의 별도 `fetch()`이므로 같은 제한이 있다고 설명하면 안 됩니다.”

**코드 근거:** [chat-api.js](../../static/js/chat-api.js)의 `REQUEST_TIMEOUT_MS`·`requestReply()`, [chat.js](../../static/js/chat.js)의 중지 버튼 이벤트, [auth.js](../../static/js/auth.js)의 인증 요청.  
**검증 코드:** [chat-api.test.mjs](../../tests/chat-api.test.mjs)의 `사용자 중지 시 HTTP 요청을 취소한다`와 `시간 초과 안내와 네트워크 오류 안내를 구분한다`. 이 테스트는 브라우저 측 취소 처리이며 서버 작업 취소를 증명하지 않습니다.

## F09. AI 답변에 HTML이나 스크립트가 들어오면 어떻게 표시되나요?

**모범 답변:** “질문과 답변, 방 제목은 요소를 만든 뒤 `textContent`로 넣기 때문에 해당 내용을 HTML로 해석하지 않습니다. 그래서 이 표시 경로에서는 답변 안의 태그가 실행 코드가 아니라 텍스트로 나타납니다. AI 답변도 외부에서 온 데이터이므로 신뢰할 수 있는 HTML이라고 가정하지 않습니다. 현재는 Markdown을 HTML로 렌더링하지 않으며, 이를 추가할 때는 별도의 안전한 변환·정제 처리가 필요합니다.”

**꼬리 질문:** `textContent`만 쓰면 서비스 전체에 XSS가 없다고 말할 수 있나요?  
**답변:** “이 코드가 처리하는 메시지와 제목 표시 경로의 방어 근거입니다. 다른 DOM 삽입 경로나 새 기능까지 포함한 전체 보안을 보장하는 말은 아닙니다.”

**코드 근거:** [chat.js](../../static/js/chat.js)의 `renderChat()`·`renderHistory()`·`setStatus()`, [auth.js](../../static/js/auth.js)의 `renderAuthUI()`.  
**추가 확인 방법:** 테스트 데이터로 HTML처럼 보이는 문자열을 표시해 문자로 보이는지 확인합니다. 기존 브라우저 테스트가 전용 XSS 검증까지 수행한다고 주장하지는 마세요.

## F10. 왼쪽 대화 목록이 곧 서버 DB의 전체 대화 기록인가요?

**모범 답변:** “현재 왼쪽 목록은 `localStorage`에 저장한 사용자별 대화 배열이고, 최대 30개를 불러옵니다. 방 ID는 프론트가 생성하고 첫 질문의 앞 30개 코드 포인트를 제목으로 쓰며, 서버는 같은 사용자와 방의 성공 대화를 조회해 AI 문맥을 만듭니다. 화면은 `GET /api/me/chats`를 호출해 목록을 복원하지 않으므로 다른 기기에서 로그인하면 기존 목록이 자동으로 보이지 않습니다. 화면의 대화 삭제도 브라우저 저장소만 바꾸며 서버 DB 기록을 삭제하지 않습니다.”

**꼬리 질문:** 여러 기기에서 같은 기록을 보게 하려면 무엇을 바꾸겠습니까?  
**답변:** “이미 있는 내 로그 API를 화면과 연결해 방별로 묶고 시간순으로 복원하는 작업이 필요합니다. 서버와 브라우저 사이의 삭제·동기화 기준도 정해야 하며, 현재 구현된 기능과는 구분해서 설명하겠습니다.”

**코드 근거:** [chat.js](../../static/js/chat.js)의 `storageKeyFor()`·`loadChats()`·`save()`·`handleSubmit()`·삭제 버튼 처리, [chat_db.py](../../app/services/chat_db.py)의 `get_history()`, [routers/chat.py](../../app/routers/chat.py)의 `get_my_chat()`.  
**검증 코드:** [test_browser_integration.py](../../tests/test_browser_integration.py)의 `test_login_room_context_and_owner_switch()`는 같은 방·새 방·새로고침·삭제 후 새 방의 문맥을 검사합니다. 다른 기기 동기화 구현을 검증하는 테스트는 아닙니다.

## F11. 요청을 기다리는 중에 로그아웃하거나 계정을 바꾸면 어떻게 되나요?

**모범 답변:** “인증 모듈이 `authchange`를 알리면 채팅 모듈이 사용자별 저장소 키를 바꾸고 해당 사용자의 목록을 불러옵니다. 소유자가 바뀌면 진행 중인 요청을 중지하며, 응답 처리에서도 요청 당시 저장소와 현재 요청이 일치하는지 확인해서 다른 계정 화면에 이전 답변이 붙는 것을 막습니다. 만료 타이머와 창 포커스·표시 상태 변화, 다른 탭의 토큰 변경 이벤트에서도 인증 화면을 갱신합니다. 이전 요청에서 늦게 온 401이 새 토큰을 지우지 않도록 `clearAuth(token)`에서 토큰 일치 여부도 검사합니다.”

**꼬리 질문:** 사용자별 저장소 키로 나누면 같은 컴퓨터의 다른 사람이 기록을 절대 못 보나요?  
**답변:** “화면에서 계정별 기록이 섞이지 않게 하는 구분일 뿐 암호화나 서버 권한 검사는 아닙니다. 현재 로그아웃은 사용자 대화 저장소까지 지우지 않으므로 공유 기기에서의 기록 보존 정책은 별도로 정해야 합니다.”

**코드 근거:** [auth.js](../../static/js/auth.js)의 `syncAuthState()`·`clearAuth()`와 이벤트 등록, [chat.js](../../static/js/chat.js)의 `switchChatOwner()`·`handleSubmit()`.  
**검증 코드:** [test_browser_integration.py](../../tests/test_browser_integration.py)의 `test_expiry_and_401_clear_token_and_login_ui()`·`test_old_request_401_does_not_remove_new_login()`.

## F12. 평가자 앞에서 프론트와 서버 연결을 어떻게 검증하겠습니까?

**모범 답변:** “먼저 브라우저에서 비로그인 질문이 차단되는지 보고, 회원가입·로그인 후 질문과 답변이 같은 화면에 나타나는지 확인하겠습니다. DevTools Network에서 `/api/chat`의 본문과 상태코드를 확인하고, 같은 사용자·방의 서버 로그와 DB 기록으로 연결하겠습니다. 같은 방의 후속 질문과 새 방 질문, 만료·오류·중지 상황에서도 화면과 인증 상태가 맞는지 확인하겠습니다. 실제 AI 응답과 외부 URL 접속 검증은 모의 AI를 쓰는 로컬 브라우저 테스트와 별도로 증빙하겠습니다.”

**꼬리 질문:** 기존 브라우저 테스트가 있으면 실제 AI와 외부 배포도 검증됐다고 할 수 있나요?  
**답변:** “아닙니다. 현재 브라우저 테스트는 로컬 서버와 테스트 DB를 사용하고 AI 동작을 모의하므로, 실제 API 키·외부 AI 통신·배포 URL의 접근 가능성은 별도 확인이 필요합니다.”

**코드 근거와 기존 검증:** [test_browser_integration.py](../../tests/test_browser_integration.py)의 `browser_page()`와 각 테스트, [chat-api.test.mjs](../../tests/chat-api.test.mjs), [테스트 안내](../testing-guide.md). 브라우저 테스트에는 `RUN_BROWSER_TESTS=1` 조건이 있으며, 파일이 있다는 사실과 이번에 실행해 통과했다는 주장은 구분합니다.
