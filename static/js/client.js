const REQUEST_TIMEOUT_MS = 30_000;

// JSON POST 요청을 보내고 응답·오류·취소·시간 초과를 처리한다.
export const client = async (url, body, { token, signal, errors = {} } = {}) => {
    // 요청 취소 오류를 발생시킨다.
    const abort_err = () => { throw new DOMException(errors.cancelled, 'AbortError') }
    if (signal?.aborted) abort_err()
    const controller = new AbortController()

    // 외부 취소 신호를 현재 요청에 전달한다.
    const abort = () => controller.abort()

    let timedOut  = false
    let requestId = null
    let response  = null

    signal?.addEventListener('abort', abort)
    // 제한 시간이 지나면 진행 중인 요청을 중단한다.
    const timer = setTimeout(() => {
        timedOut = true
        controller.abort()
    }, REQUEST_TIMEOUT_MS)

    try {
        const headers = { 'Content-Type': 'application/json' }
        if (token) headers.Authorization = `Bearer ${token}`

        response = await fetch(url, {
            method : 'POST',
            headers,
            body   : JSON.stringify(body),
            signal : controller.signal
        })

        requestId  = response.headers?.get('X-Request-ID') || null
        const data = await response.json()

        if (controller.signal.aborted) abort_err()
        if (!response.ok) {
            const detail  = data?.detail    ?? data
            const message = detail?.message ?? null
            const error   = new Error(message || errors[response.status] || errors.default)

            error.status    = response.status
            error.errorCode = detail?.error_code ?? null
            error.requestId = detail?.request_id ?? requestId

            throw error
        }
        return { data, requestId }
    } catch (e) {
        if (signal?.aborted) abort_err()
        if (timedOut) {
            const timeout     = new Error(errors.timeout)
            timeout.errorCode = 'CLIENT_TIMEOUT'
            timeout.requestId = requestId
            throw timeout
        }
        if (e instanceof SyntaxError) {
            const error     = new Error(errors[response.status] || errors.default)
            error.status    = response.status
            error.errorCode = null
            error.requestId = requestId
            throw error
        }
        if (e instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 연결 상태를 확인해주세요.')
        throw e
    } finally {
        clearTimeout(timer)
        signal?.removeEventListener('abort', abort)
    }
}
