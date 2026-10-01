// ==============================================================================
// [인증 데이터 담당: auth-service.js]
// 이전 auth.js에서 HTTP 요청과 토큰 읽기를 분리했다. 모달·버튼 조작은 auth-ui.js가 맡는다.
// 사용자 여정: auth-ui.submitAuth → request_auth → client → /auth/login 또는 /auth/register.
// 서버가 반환한 토큰의 저장은 auth-ui.js, 이 파일은 기존 토큰의 읽기·만료 확인·삭제를 담당한다.
// JWT payload를 읽는 것은 화면 표시용 디코딩이다. 서명 검증은 서버 get_token_id()가 수행한다.
// ==============================================================================
import { client } from './client.js';

// 서버의 안내가 없거나 본문을 읽지 못했을 때 사용할 인증 전용 기본 문구.
// 동일한 HTTP 401도 채팅에서는 재로그인 안내, 인증 폼에서는 자격증명 확인 안내가 필요하다.
const ERROR_MESSAGES = {
    401       : '아이디 또는 비밀번호를 확인해 주세요.',
    409       : '이미 사용 중인 아이디입니다.',
    422       : '아이디와 비밀번호 입력을 확인해 주세요.',
    default   : '인증 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
    cancelled : '인증 요청을 취소했습니다.',
    timeout   : '인증 요청 시간이 초과됐습니다. 다시 시도해 주세요.',
};

// 로그인·회원가입 요청을 서버로 보낸다.
// { id, pw }는 백엔드 AuthRequest 계약이다. 비밀번호를 이 함수에서 trim하지 않는다.
// async 키워드가 없어도 client()의 Promise를 그대로 반환하므로 호출자는 await할 수 있다.
export const request_auth = (url, id, pw, signal) => client(url, { id, pw }, { signal, errors: ERROR_MESSAGES })

// 저장된 토큰의 사용자 정보를 읽고 잘못된 토큰을 삭제한다.
// [반환값 주의] 이름은 getTokenID지만 ID 문자열이 아닌 { id, exp, ... } claims 객체를 반환한다.
// 토큰이 없거나 저장소 읽기가 실패하면 null, 삭제 경로에서는 removeToken()의 undefined가 된다.
// auth-ui.js는 이 차이를 ?? null로 정리한다. 토큰 문자열은 별도로 읽어 auth.token에 보관한다.
export const getTokenID = () => {
    let token
    let claims

    try {
        token = localStorage.getItem('access_token')
        // Header.Payload.Signature에서 가운데 payload를 선택한다. 전자 서명 확인은 하지 않는다.
        const payload = token?.split('.')[1]
        if (payload) {
            // Base64URL의 -/_를 +/로 복원 → atob으로 바이트 읽기 → UTF-8 TextDecoder로 한글 복원.
            // JSON.parse는 마지막 JSON 문자열을 JS 객체로 바꾸는 단계다.
            const bytes = Uint8Array.from(atob(payload.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
            claims      = JSON.parse(new TextDecoder().decode(bytes))
        }
    } catch {
        // 읽기부터 실패하면 token은 undefined다. 이 경우 삭제를 시도하지 않고 비로그인으로 돌려준다.
        // 읽은 후 디코딩이 실패한 경우는 아래 검사를 거쳐 잘못된 저장값을 제거한다.
        if (token === undefined) return null
    }

    if (token === null) return null
    // exp는 초 단위, Date.now()는 밀리초 단위이므로 * 1000으로 비교 단위를 맞춘다.
    // 현재 클라이언트는 id의 존재와 exp의 유한 숫자·만료를 확인한다. 엄격한 ID 타입·서명 검증은 서버 책임이다.
    if (!claims?.id || !Number.isFinite(claims.exp) || claims.exp * 1000 <= Date.now()) return removeToken()

    return claims
}

// 저장된 로그인 토큰을 삭제한다.
// 반환값이 없는 블록 화살표 함수다. 브라우저 토큰 삭제이며 서버 토큰 폐기 API 호출은 아니다.
// 저장소 접근이 차단되어 removeItem이 실패하면 예외를 auth-ui.js의 호출부로 전달한다.
export const removeToken = () => { localStorage.removeItem('access_token') }
