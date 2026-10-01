// ==============================================================================
// [인증 화면과 로그인 상태의 조정자: auth-ui.js]
// 이전 auth.js의 모달·이벤트·토큰 저장·상태 동기화를 담당한다. HTTP 처리는 auth-service → client로 위임한다.
// 사용자 여정: 폼 제출 → 입력 검증 → 인증 요청 → 토큰 저장 → syncAuthState → authchange → 채팅 계정 전환.
// 현재 서버는 가입 성공에도 토큰을 주므로 회원가입과 로그인 모두 같은 로그인 완료 경로를 사용한다.
// 핵심 질문: "늦게 온 응답이 사용자가 이미 바꾼 계정/닫은 창을 다시 덮어쓰지 않는가?"
// 이를 위해 pendingAuth(요청 객체), 요청 당시 token, rejectedToken을 각각 비교한다.
// ==============================================================================
import { request_auth, getTokenID, removeToken } from './auth-service.js'
import { toast } from './toast.js'

// $는 첫 요소, $$는 일치하는 요소 목록을 고르는 약식 함수이며 jQuery가 아니다.
const $  = selector => document.querySelector(selector)
const $$ = selector => document.querySelectorAll(selector)

// [ES 모듈 live binding] 가져간 쪽은 auth의 갱신된 값을 읽지만 직접 재할당하지는 않는다.
// null은 비로그인, 로그인 시에는 디코딩된 claims에 원문 token을 붙여 보관한다.
// 이 객체는 UI 상태이며, 신뢰할 수 있는 사용자 판정은 서버의 JWT 검증이 최종 담당한다.
export let auth = null

// signup: 모달 모드 / timer: 만료 예약 / pendingAuth: 현재 요청 / rejectedToken: 이 탭에서 거부한 토큰.
// rejectedToken은 저장소 삭제가 실패해도 같은 토큰을 곧바로 다시 로그인 상태로 읽지 않게 한다.
// 메모리 상태라 새로고침 이후까지 유지되는 서버 차단 목록은 아니다.
let signup        = false
let timer         = null
let pendingAuth   = null
let rejectedToken = null

// 인증 요청 중 폼 입력을 잠그거나 해제한다.
// disabled는 조작을 막고, aria-busy는 보조기술에 처리 중임을 알린다. 역할이 다르다.
const setAuthBusy = busy => {
    $('.auth-form').setAttribute('aria-busy', String(busy))
    $$('.auth-form input, .auth-submit, [data-tab]').forEach(element => element.disabled = busy)
}

// 진행 중인 인증 요청을 취소하고 폼을 다시 활성화한다.
// abort만으로는 이미 돌아오는 응답을 모두 막을 수 없어 pendingAuth도 null로 바꾼다.
// submitAuth의 동일 요청 검사와 함께 사용한다. 서버에서 이미 만든 계정까지 되돌리는 작업은 아니다.
const cancelAuthRequest = () => {
    pendingAuth?.controller.abort()
    pendingAuth = null
    setAuthBusy(false)
}

// 로그인 상태에 맞춰 화면과 만료 타이머를 갱신한다.
// [동기화 순서] 이전 타이머 제거 → 저장소/claims 읽기 → 오래된 인증 요청 취소 → DOM → 이벤트 → 새 타이머.
// reason은 채팅에 전달하는 전환 이유다. 만료/401이면 초안 복원, 명시적 로그아웃이면 정리에 사용한다.
export const syncAuthState = (reason = 'expired') => {
    clearTimeout(timer)
    let token = null

    try {
        token = localStorage.getItem('access_token')
        // 거부한 토큰은 재사용하지 않는다. getTokenID의 null/undefined도 한 가지 null 상태로 정리한다.
        auth  = token === rejectedToken ? null : getTokenID() ?? null
        if (auth) auth.token = token
    } catch {
        // 저장소 읽기/삭제 실패 시 화면에서는 로그인 상태를 유지하지 않고 지속 안내를 표시한다.
        auth          = null
        rejectedToken = token ?? rejectedToken
        toast('로그인 정보를 확인하거나 삭제하지 못했습니다. 브라우저 저장소 설정을 확인해 주세요.', 0)
    }

    // 요청을 시작했을 때의 계정과 현재 계정이 다르면 이전 인증 응답을 받을 자격도 없어졌다고 본다.
    if (token       && token             !== rejectedToken && !auth) reason = 'expired'
    if (pendingAuth && pendingAuth.token !== (auth?.token ?? null))  cancelAuthRequest()

    const id = auth?.id
    $('.header-user')     .hidden      = !auth

    // textContent는 ID를 HTML로 실행하지 않고 표시한다. hidden/textContent/aria-label을 함께 맞춘다.
    $('.header-user')     .textContent = id || ''
    $('.login-button')    .textContent = auth ? '로그아웃' : '로그인'
    $('.profile .avatar') .textContent = auth ? id[0].toUpperCase() : 'G'
    $('.profile strong')  .textContent = id || '게스트'
    $('.profile small')   .textContent = auth ? '로그아웃' : '로그인하여 이어가기'

    $('.profile')         .setAttribute('aria-label', auth ? `${id} 계정 로그아웃` : '로그인')

    // [이벤트로 상태 전달] chat-ui가 듣고 chat-action.switchChatOwner를 호출한다.
    // dispatchEvent의 리스너는 이 호출 중 실행되므로 채팅 요청 취소·초안 처리도 여기서 이어질 수 있다.
    window.dispatchEvent(new CustomEvent('authchange', { detail: { id: id ?? null, reason } }))
    // exp(초) → ms로 변환. 지나치게 큰 타이머 값은 제한하고, 깨어났을 때 토큰을 다시 검사한다.
    if (auth) timer = setTimeout(syncAuthState, Math.min(auth.exp * 1000 - Date.now(), 2_147_483_647))
}

// 현재 토큰이 삭제 대상과 같으면 로그아웃을 처리한다.
// [늦은 401 방어] 토큰 A로 보낸 요청이 실패할 때 사용자가 이미 토큰 B로 로그인했을 수 있다.
// A와 현재 저장값이 다르면 B를 지우지 않고 현재 상태만 다시 읽는다.
export const clearAuth = (token = auth?.token, reason = 'unauthorized') => {
    try {
        if (token && token !== localStorage.getItem('access_token')) return syncAuthState('storage')
        removeToken()
    } catch {
        rejectedToken = token ?? rejectedToken
        toast('로그인 정보를 삭제하지 못했습니다. 새로고침하면 이전 정보가 남아 있을 수 있습니다.', 0)
    }
    syncAuthState(reason)
}

// 로그인·회원가입 모드에 맞춰 인증 폼을 전환한다.
// 폼 두 개를 만들지 않고 signup 플래그로 탭·제목·비밀번호 확인 필드·자동완성 목적을 함께 바꾼다.
const setAuthMode = value => {
    signup = value
    $$('[data-tab]').forEach(tab => tab.classList.toggle('active', (tab.dataset.tab === 'signup') === signup))

    $('.auth-title')    .textContent  = signup ? '새로운 대화를 시작해요.' : '다시 만나 반가워요.'
    $('.confirm-wrap')  .hidden       = !signup
    $('.auth-confirm')  .required     = signup
    $('.auth-password') .autocomplete = signup ? 'new-password' : 'current-password'
    $('.auth-password') .placeholder  = '8자 이상, UTF-8 72바이트 이내'
    $('.auth-submit')   .textContent  = signup ? '회원가입' : '로그인'
    $('.auth-status')   .textContent  = ''
}

// 진행 중인 인증 요청을 취소하고 로그인 창을 연다.
// 이미 열린 dialog에 showModal을 반복하지 않도록 open을 확인하고, 아이디 입력으로 포커스를 옮긴다.
export const openLogin = () => {
    cancelAuthRequest()
    setAuthMode(false)
    if (!$('.auth-dialog').open) $('.auth-dialog').showModal()
    $('.auth-name').focus()
}

// 입력값을 확인하고 인증 요청 결과를 화면에 반영한다.
// [submitAuth 파이프라인]
// 1) 기본 폼 이동 방지·중복 제출 차단  2) 문자/바이트 검증  3) 요청 신분표(request) 생성
// 4) await 인증 통신  5) 요청·모달·토큰이 여전히 같은지 검사  6) 저장·동기화·모달 닫기.
const submitAuth = async event => {
    // 폼 기본 제출로 페이지가 이동하지 않게 하고, 아래 fetch 기반 흐름으로 직접 처리한다.
    event.preventDefault()
    if (pendingAuth) return
    const id       = $('.auth-name').value.trim()
    const pw       = $('.auth-password').value
    const status   = $('.auth-status')
    const idLength = Array.from(id).length

    // ID는 앞뒤 공백을 없애지만 pw 값은 보존한다. 비밀번호 앞뒤 공백도 실제 비밀번호의 일부다.
    // Array.from(...).length는 코드 포인트 수, TextEncoder는 UTF-8 바이트 수를 센다.
    // 서버 validate_auth와 같은 3~50자 ID / 8자 이상·72바이트 이하 비밀번호 기준을 적용한다.
    if (idLength < 3 || idLength > 50)             return status.textContent = '아이디는 3~50자로 입력해 주세요.'
    if (!pw.trim())                                return status.textContent = '비밀번호를 입력해 주세요.'
    if (Array.from(pw).length < 8)                 return status.textContent = '비밀번호는 8자 이상으로 입력해 주세요.'
    if (new TextEncoder().encode(pw).length > 72)  return status.textContent = '비밀번호는 UTF-8 기준 72바이트 이내로 입력해 주세요.'
    if (signup && pw !== $('.auth-confirm').value) return status.textContent = '비밀번호가 서로 다릅니다.'

    // request 객체 자체의 동일성(===)은 요청 구분용이다. token은 시작 당시의 계정 상태 스냅샷이다.
    const request = { controller: new AbortController(), token: auth?.token ?? null }
    pendingAuth = request
    setAuthBusy(true)
    status.textContent = signup ? '회원가입 중입니다…' : '로그인 중입니다…'

    try {
        const { data } = await request_auth(signup ? '/auth/register' : '/auth/login', id, pw, request.controller.signal)
        // 기다리는 사이 창을 닫거나 새 요청이 시작됐으면 이전 결과를 화면에 적용하지 않는다.
        if (pendingAuth !== request || !$('.auth-dialog').open) return

        const token = localStorage.getItem('access_token')
        // 다른 탭이 로그인 상태를 바꾼 경우도 저장소에서 다시 비교하여 덮어쓰지 않는다.
        if (request.token !== (token === rejectedToken ? null : token)) return

        // 가입/로그인 모두 서버가 발급한 token을 같은 경로로 저장한다. 저장 실패면 로그인 완료로 표시하지 않는다.
        try   { localStorage.setItem('access_token', data.token) }
        catch { return status.textContent = '로그인 정보를 저장하지 못했습니다. 브라우저 저장소 설정을 확인해 주세요.' }
        rejectedToken = null
        // 새 토큰을 읽어 화면·채팅 계정을 전환한다. 그 과정에서 이전 pendingAuth가 취소/정리될 수도 있다.
        syncAuthState('login')
        if (!auth) return status.textContent = '유효한 로그인 정보를 받지 못했습니다. 다시 시도해 주세요.'

        $('.auth-dialog').close()
    } catch (error) {
        // 현재 열려 있는 요청의 실제 오류만 보여준다. 사용자가 창을 닫으며 취소한 경우에는 오류를 덧씌우지 않는다.
        if (pendingAuth === request && $('.auth-dialog').open && error.name !== 'AbortError') {
            status.textContent = error.message || '인증 요청에 실패했습니다.'
        }
    } finally {
        // 이전 요청의 finally가 새 요청의 잠금까지 풀지 않도록 자신이 아직 현재 요청인지 확인한다.
        if (pendingAuth === request) {
            pendingAuth = null
            setAuthBusy(false)
        }
    }
}

// 인증 버튼·탭·폼의 이벤트를 연결한다.
// 함수 선언 시에는 등록하지 않고, 파일 하단 bindAuthEvents() 호출 시 addEventListener가 실행된다.
const bindAuthEvents = () => {
    // 로그인 상태에 따라 로그아웃하거나 로그인 창을 연다.
    $$('[data-auth]').forEach(button => button.addEventListener('click', () => {
        syncAuthState()
        if (auth) clearAuth(auth.token, 'logout')
        else openLogin()
    }))
    // 닫기 버튼을 누르면 인증 요청과 창을 닫는다.
    $('[data-close]').addEventListener('click', () => {
        cancelAuthRequest()
        $('.auth-dialog').close()
    })
    $('.auth-dialog').addEventListener('cancel', cancelAuthRequest)
    // 인증 창이 닫히면 입력값과 안내를 초기화한다.
    // cancel은 Escape 등 닫기 요청, close는 실제 닫힌 뒤의 정리 지점이다.
    $('.auth-dialog').addEventListener('close', () => {
        if ($('.auth-dialog').open) return
        cancelAuthRequest()
        $('.auth-form').reset()
        $('.auth-status').textContent = ''
    })
    // 선택한 탭에 맞춰 로그인·회원가입 모드를 전환한다.
    $$('[data-tab]').forEach(button => button.addEventListener('click', () => {
        if (!pendingAuth) setAuthMode(button.dataset.tab === 'signup')
    }))
    $('.auth-form').addEventListener('submit', submitAuth)
}

// ==============================================================================
// [모듈 초기 실행과 브라우저 생명주기]
// type="module"은 기본적으로 HTML 파싱 후 실행한다. import된 의존 모듈이 먼저 평가된다.
// 같은 페이지의 같은 모듈 URL은 공유되므로 chat-ui가 import해도 이 초기화가 매번 반복되지는 않는다.
// Python의 __main__ 조건과 달리, 여기의 최상위 코드는 import로 로드될 때도 실행된다.
// ==============================================================================
syncAuthState()
bindAuthEvents()

// 다른 탭에서 바뀐 로그인 정보를 화면에 반영한다.
// 같은 탭에서 한 setItem은 이 탭의 storage 이벤트로 처리하지 않으므로 저장 직후 직접 동기화한다.
// event.key === null인 clear()도 반영하고, sessionStorage 등 다른 저장소 이벤트는 제외한다.
window.addEventListener('storage', event => {
    if (event.storageArea            && event.storageArea !== localStorage) return
    if (event.key !== 'access_token' && event.key         !== null)         return
    syncAuthState('storage')
})

// 창으로 돌아오면 로그인 상태를 확인한다.
window.addEventListener('focus', () => syncAuthState())

// 화면이 다시 표시되면 로그인 상태를 확인한다.
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) syncAuthState()
})
