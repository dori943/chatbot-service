// ==============================================================================
// [공통 HTTP 통신 담당: client.js]
// 이전 chat-api.js의 전송·오류·취소 처리를 인증과 채팅이 함께 쓰는 함수로 분리했다.
// - auth-service.js: 인증 URL + { id, pw } + 인증용 안내 문구를 전달한다.
// - chat-service.js: /api/chat + 방 정보·질문 + JWT + 채팅용 안내 문구를 전달한다.
// - 이 파일: JSON POST 전송 → 응답 해석 → 오류 분류 → 타이머·리스너 정리만 담당한다.
// 화면 표시나 로그아웃은 호출한 UI/액션 모듈의 책임이다. DOM 없이 통신 테스트가 가능하다.
// 성공 계약은 답변 문자열이 아닌 { data, requestId }이며, data의 업무별 필드를 검사하지 않는다.
// 예: data.answer가 정상인지 확인하는 백엔드 로직과 HTTP 성공 판정은 서로 다른 검사다.
// ==============================================================================

// 인증·채팅 모두에 적용되는 브라우저 대기 제한. 서버 AI 타임아웃과 별개다.
const REQUEST_TIMEOUT_MS = 30_000;

// JSON POST 요청을 보내고 응답·오류·취소·시간 초과를 처리한다.
// [매개변수 구조 분해]
// 세 번째 인자의 { token, signal, errors = {} }에서 필요한 옵션을 꺼낸다.
// 바깥의 = {}는 옵션 자체를 생략한 호출도 허용한다. null을 전달하는 경우까지 대체하지는 않는다.
// async 함수의 return은 Promise 성공, throw는 Promise 실패가 되어 호출자의 await에 전달된다.
export const client = async (url, body, { token, signal, errors = {} } = {}) => {
    // 요청 취소 오류를 발생시킨다.
    const abort_err = () => { throw new DOMException(errors.cancelled, 'AbortError') }
    // optional chaining(?.): 외부 signal을 주지 않았다면 접근을 생략한다.
    if (signal?.aborted) abort_err()
    const controller = new AbortController()

    // 외부 취소 신호를 현재 요청에 전달한다.
    // 외부 signal은 읽는 신호이고, 내부 controller는 실제 fetch 중단을 명령할 객체다.
    // 사용자 중지와 자체 30초 제한이 같은 내부 controller를 사용하도록 중간 연결을 둔다.
    const abort = () => controller.abort()

    let timedOut  = false
    let requestId = null
    let response  = null

    signal?.addEventListener('abort', abort)
    // 제한 시간이 지나면 진행 중인 요청을 중단한다.
    // abort 오류 자체만 보면 사용자 중지인지 시간 초과인지 모르므로 원인을 별도 기록한다.
    const timer = setTimeout(() => {
        timedOut = true
        controller.abort()
    }, REQUEST_TIMEOUT_MS)

    try {
        const headers = { 'Content-Type': 'application/json' }
        // 인증 요청에는 기존 토큰이 필요 없고, 채팅 요청에만 호출자가 토큰을 제공한다.
        if (token) headers.Authorization = `Bearer ${token}`

        // JSON.stringify: JS 객체 → HTTP 본문의 JSON 문자열.
        // await는 응답을 기다리는 동안 이 함수의 후속 실행을 미루며 다른 이벤트 처리를 허용한다.
        response = await fetch(url, {
            method : 'POST',
            headers,
            body   : JSON.stringify(body),
            signal : controller.signal
        })

        // JSON 파싱이 실패해도 요청을 추적할 수 있도록 헤더의 ID를 먼저 확보한다.
        requestId  = response.headers?.get('X-Request-ID') || null
        const data = await response.json()

        // 헤더 수신 이후 본문을 읽는 도중 취소된 요청도 성공 결과로 넘기지 않는다.
        if (controller.signal.aborted) abort_err()
        // fetch는 401·500 같은 HTTP 오류에도 Response를 반환하므로 ok 검사가 따로 필요하다.
        if (!response.ok) {
            // ??는 null/undefined일 때만 오른쪽을 선택한다. 빈 문자열·0까지 대체하는 ||와 다르다.
            // FastAPI의 detail 안쪽 형식과 우리 서비스의 최상위 오류 형식을 모두 읽는다.
            const detail  = data?.detail    ?? data
            const message = detail?.message ?? null
            const error   = new Error(message || errors[response.status] || errors.default)

            // 상위 액션이 401 재로그인·시간 초과 재시도·요청 ID 표시를 결정할 수 있게 정보를 보존한다.
            error.status    = response.status
            error.errorCode = detail?.error_code ?? null
            error.requestId = detail?.request_id ?? requestId

            throw error
        }
        return { data, requestId }
    } catch (e) {
        // [분류 순서] 명시적 사용자 취소 → 클라이언트 시간 초과 → JSON 오류 → 네트워크 오류.
        // 둘 다 AbortController를 쓰지만 CLIENT_TIMEOUT과 AbortError는 화면에서 다르게 다룬다.
        if (signal?.aborted) abort_err()
        if (timedOut) {
            const timeout     = new Error(errors.timeout)
            timeout.errorCode = 'CLIENT_TIMEOUT'
            timeout.requestId = requestId
            throw timeout
        }
        if (e instanceof SyntaxError) {
            // 프록시 등이 JSON 대신 HTML/문자열을 보내면 response.json()이 실패할 수 있다.
            // 상태코드와 헤더 ID는 보존하고, 파싱하지 못한 본문 대신 서비스별 기본 문구를 쓴다.
            const error     = new Error(errors[response.status] || errors.default)
            error.status    = response.status
            error.errorCode = null
            error.requestId = requestId
            throw error
        }
        if (e instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 연결 상태를 확인해주세요.')
        // 위에서 이미 분류한 HTTP 오류 등은 정보가 사라지지 않도록 그대로 호출자에게 전파한다.
        throw e
    } finally {
        // 성공·실패·중지 어느 경로든 정리: 끝난 요청의 타이머나 취소 리스너를 남겨두지 않는다.
        // 브라우저 fetch 취소는 서버의 AI 호출·DB 저장 취소까지 보장하는 기능은 아니다.
        clearTimeout(timer)
        signal?.removeEventListener('abort', abort)
    }
}
