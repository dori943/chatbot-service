import { client } from './client.js';

const ERROR_MESSAGES = {
    401       : '아이디 또는 비밀번호를 확인해 주세요.',
    409       : '이미 사용 중인 아이디입니다.',
    422       : '아이디와 비밀번호 입력을 확인해 주세요.',
    default   : '인증 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
    cancelled : '인증 요청을 취소했습니다.',
    timeout   : '인증 요청 시간이 초과됐습니다. 다시 시도해 주세요.',
};

// 로그인·회원가입 요청을 서버로 보낸다.
export const request_auth = (url, id, pw, signal) => client(url, { id, pw }, { signal, errors: ERROR_MESSAGES })

// 저장된 토큰의 사용자 정보를 읽고 잘못된 토큰을 삭제한다.
export const getTokenID = () => {
    let token
    let claims

    try {
        token = localStorage.getItem('access_token')
        const payload = token?.split('.')[1]
        if (payload) {
            const bytes = Uint8Array.from(atob(payload.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
            claims      = JSON.parse(new TextDecoder().decode(bytes))
        }
    } catch {
        if (token === undefined) return null
    }

    if (token === null) return null
    if (!claims?.id || !Number.isFinite(claims.exp) || claims.exp * 1000 <= Date.now()) return removeToken()

    return claims
}

// 저장된 로그인 토큰을 삭제한다.
export const removeToken = () => { localStorage.removeItem('access_token') }
