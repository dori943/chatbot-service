import { request_auth, getTokenID, removeToken } from './auth-service.js'
import { toast } from './toast.js'

const $  = selector => document.querySelector(selector)
const $$ = selector => document.querySelectorAll(selector)

const errors = {
    login  : '로그인에 실패했습니다.',
    server : '서버 상태가 좋지 않습니다. 잠시 후 다시 시도해 주세요.',
}

export let auth = null

let signup        = false
let timer         = null
let pendingAuth   = null
let rejectedToken = null

// 인증 요청 중 폼 입력을 잠그거나 해제한다.
const setAuthBusy = busy => {
    $('.auth-form').setAttribute('aria-busy', String(busy))
    $$('.auth-form input, .auth-submit, [data-tab]').forEach(element => element.disabled = busy)
}

// 진행 중인 인증 요청을 취소하고 폼을 다시 활성화한다.
const cancelAuthRequest = () => {
    pendingAuth?.controller.abort()
    pendingAuth = null
    setAuthBusy(false)
}

// 로그인 상태에 맞춰 화면과 만료 타이머를 갱신한다.
export const syncAuthState = (reason = 'expired') => {
    clearTimeout(timer)
    let token = null

    try {
        token = localStorage.getItem('access_token')
        auth  = token === rejectedToken ? null : getTokenID() ?? null
        if (auth) auth.token = token
    } catch {
        auth          = null
        rejectedToken = token ?? rejectedToken
        toast('로그인 정보를 확인하거나 삭제하지 못했습니다. 브라우저 저장소 설정을 확인해 주세요.', 0)
    }

    if (token       && token             !== rejectedToken && !auth) reason = 'expired'
    if (pendingAuth && pendingAuth.token !== (auth?.token ?? null))  cancelAuthRequest()

    const id = auth?.id
    $('.header-user')     .hidden      = !auth

    $('.header-user')     .textContent = id || ''
    $('.login-button')    .textContent = auth ? '로그아웃' : '로그인'
    $('.profile .avatar') .textContent = auth ? id[0].toUpperCase() : 'G'
    $('.profile strong')  .textContent = id || '게스트'
    $('.profile small')   .textContent = auth ? '로그아웃' : '로그인하여 이어가기'

    $('.profile')         .setAttribute('aria-label', auth ? `${id} 계정 로그아웃` : '로그인')

    window.dispatchEvent(new CustomEvent('authchange', { detail: { id: id ?? null, reason } }))
    if (auth) timer = setTimeout(syncAuthState, Math.min(auth.exp * 1000 - Date.now(), 2_147_483_647))
}

// 현재 토큰이 삭제 대상과 같으면 로그아웃을 처리한다.
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
const setAuthMode = value => {
    signup = value
    $$('[data-tab]').forEach(tab => tab.classList.toggle('active', (tab.dataset.tab === 'signup') === signup))

    $('.auth-title')    .textContent  = signup ? '새로운 대화를 시작해요.' : '다시 만나 반가워요.'
    $('.auth-form')     .noValidate   = !signup
    $('.confirm-wrap')  .hidden       = !signup
    $('.auth-confirm')  .required     = signup
    $('.auth-password') .autocomplete = signup ? 'new-password' : 'current-password'
    $('.auth-password') .placeholder  = signup ? '8자 이상으로 입력해주세요.' : '비밀번호를 입력하세요'
    $('.auth-submit')   .textContent  = signup ? '회원가입' : '로그인'
    $('.auth-status')   .textContent  = ''
}

// 진행 중인 인증 요청을 취소하고 로그인 창을 연다.
export const openLogin = () => {
    cancelAuthRequest()
    setAuthMode(false)
    if (!$('.auth-dialog').open) $('.auth-dialog').showModal()
    $('.auth-name').focus()
}

// 입력값을 확인하고 인증 요청 결과를 화면에 반영한다.
const submitAuth = async event => {
    event.preventDefault()
    if (pendingAuth) return
    const id       = $('.auth-name').value.trim()
    const pw       = $('.auth-password').value
    const status   = $('.auth-status')
    const idLength = Array.from(id).length

    if (idLength < 3 || idLength > 50)             return status.textContent = signup ? '아이디는 3~50자로 입력해 주세요.' : errors.login
    if (!pw.trim())                                return status.textContent = signup ? '비밀번호를 입력해 주세요.' : errors.login
    if (Array.from(pw).length < 8)                 return status.textContent = signup ? '비밀번호는 8자 이상으로 입력해 주세요.' : errors.login
    if (new TextEncoder().encode(pw).length > 72)  return status.textContent = signup ? '비밀번호가 너무 깁니다. 더 짧게 입력해 주세요.' : errors.login
    if (signup && pw !== $('.auth-confirm').value) return status.textContent = '비밀번호가 서로 다릅니다.'

    const request = { controller: new AbortController(), token: auth?.token ?? null }
    pendingAuth = request
    setAuthBusy(true)
    status.textContent = signup ? '회원가입 중입니다…' : '로그인 중입니다…'

    try {
        const { data } = await request_auth(signup ? '/auth/register' : '/auth/login', id, pw, request.controller.signal)
        if (pendingAuth !== request || !$('.auth-dialog').open) return

        const token = localStorage.getItem('access_token')
        if (request.token !== (token === rejectedToken ? null : token)) return

        try   { localStorage.setItem('access_token', data.token) }
        catch { return status.textContent = signup ? '로그인 정보를 저장하지 못했습니다. 브라우저 저장소 설정을 확인해 주세요.' : errors.server }
        rejectedToken = null
        syncAuthState('login')
        if (!auth) return status.textContent = signup ? '유효한 로그인 정보를 받지 못했습니다. 다시 시도해 주세요.' : errors.server

        $('.auth-dialog').close()
    } catch (error) {
        if (pendingAuth === request && $('.auth-dialog').open && error.name !== 'AbortError') {
            if (signup) status.textContent = error.message || '인증 요청에 실패했습니다.'
            else status.textContent = [400, 401, 403, 422].includes(error.status) ? errors.login : errors.server
        }
    } finally {
        if (pendingAuth === request) {
            pendingAuth = null
            setAuthBusy(false)
        }
    }
}

// 인증 버튼·탭·폼의 이벤트를 연결한다.
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

syncAuthState()
bindAuthEvents()

// 다른 탭에서 바뀐 로그인 정보를 화면에 반영한다.
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
