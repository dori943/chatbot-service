import { requestAuthentication } from './auth-api.js';

const elements = new Map();
let rejectedToken = null;

export function getAccessToken() {
  try {
    const token = localStorage.getItem('access_token');
    return token === rejectedToken ? null : token;
  } catch (_) {
    return null;
  }
}

function getTokenClaims(token = getAccessToken()) {
  try {
    const payload = token?.split('.')[1];
    if (!payload) return null;
    // JWT의 UTF-8 사용자 ID를 복원한다. 실제 서명 검증은 백엔드가 수행한다.
    const bytes = Uint8Array.from(atob(payload.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
    const claims = JSON.parse(new TextDecoder().decode(bytes));
    return claims;
  } catch (_) {
    return null;
  }
}

export function getAuthenticatedId(token = getAccessToken()) {
  const claims = getTokenClaims(token);
  if (!Number.isFinite(claims?.exp) || claims.exp * 1000 <= Date.now()) return null;
  return typeof claims.id === 'string' && claims.id ? claims.id : null;
}

function getElement(id) {
  if (!elements.has(id)) elements.set(id, document.getElementById(id));
  return elements.get(id);
}

let signup = false;
let expiryTimer;
let pendingAuth = null;

function setAuthBusy(busy) {
  getElement('auth-form').setAttribute('aria-busy', String(busy));
  document.querySelectorAll('#auth-form input, .auth-submit, [data-tab]').forEach(element => element.disabled = busy);
}

function cancelAuthRequest() {
  pendingAuth?.controller.abort();
  pendingAuth = null;
  setAuthBusy(false);
}

function removeToken(token) {
  try {
    localStorage.removeItem('access_token');
  } catch (_) {
    // 저장소 삭제가 실패해도 거절된 토큰으로 새 요청을 보내지 않는다.
    rejectedToken = token;
    getElement('toast').textContent = '로그인 정보를 삭제하지 못했습니다. 새로고침하면 이전 정보가 남아 있을 수 있습니다.';
    getElement('toast').hidden = false;
  }
}

function renderAuthUI() {
  const id = getAuthenticatedId();
  const loggedIn = Boolean(id);
  getElement('header-user').textContent = id || '';
  getElement('header-user').hidden = !loggedIn;
  document.querySelector('.login-button').textContent = loggedIn ? '로그아웃' : '로그인';
  document.querySelector('.profile .avatar').textContent = loggedIn ? id[0].toUpperCase() : 'G';
  document.querySelector('.profile strong').textContent = id || '게스트';
  document.querySelector('.profile small').textContent = loggedIn ? '로그아웃' : '로그인하여 이어가기';
  document.querySelector('.profile').setAttribute('aria-label', loggedIn ? `${id} 계정 로그아웃` : '로그인');
}

function notifyAuthChange(reason) {
  window.dispatchEvent(new CustomEvent('authchange', { detail: { id: getAuthenticatedId(), reason } }));
}

function syncAuthState(reason = 'expired') {
  clearTimeout(expiryTimer);
  const token = getAccessToken();
  if (token && !getAuthenticatedId()) {
    removeToken(token);
    reason = 'expired';
  }
  if (pendingAuth && pendingAuth.token !== getAccessToken()) cancelAuthRequest();
  renderAuthUI();
  notifyAuthChange(reason);
  const claims = getTokenClaims();
  if (getAuthenticatedId()) {
    expiryTimer = setTimeout(syncAuthState, Math.min(claims.exp * 1000 - Date.now(), 2_147_483_647));
  }
}

export function clearAuth(token = getAccessToken(), reason = 'unauthorized') {
  // 이전 요청의 401이 새로 로그인한 토큰까지 삭제하지 않게 한다.
  if (token !== getAccessToken()) return;
  if (token) removeToken(token);
  syncAuthState(reason);
}

function setAuthMode(value) {
  signup = value;
  document.querySelectorAll('[data-tab]').forEach(tab => tab.classList.toggle('active', (tab.dataset.tab === 'signup') === signup));
  getElement('auth-title').textContent = signup ? '새로운 대화를 시작해요.' : '다시 만나 반가워요.';
  getElement('confirm-wrap').hidden = !signup;
  getElement('auth-confirm').required = signup;
  getElement('auth-password').autocomplete = signup ? 'new-password' : 'current-password';
  getElement('auth-password').placeholder = signup ? '8자 이상, UTF-8 72바이트 이내' : '비밀번호를 입력하세요';
  document.querySelector('.auth-submit').textContent = signup ? '회원가입' : '로그인';
  getElement('auth-status').textContent = '';
}

export function openLogin() {
  cancelAuthRequest();
  setAuthMode(false);
  if (!getElement('auth-dialog').open) getElement('auth-dialog').showModal();
  getElement('auth-name').focus();
}

// 인증 모달의 입력과 탭 전환을 처리합니다.
function bindAuthEvents() {
  document.querySelectorAll('[data-auth]').forEach(button => button.addEventListener('click', () => {
    if (getAuthenticatedId()) {
      clearAuth(getAccessToken(), 'logout');
      return;
    }
    openLogin();
  }));
  document.querySelector('[data-close]').addEventListener('click', () => {
    cancelAuthRequest();
    getElement('auth-dialog').close();
  });
  getElement('auth-dialog').addEventListener('cancel', cancelAuthRequest);
  getElement('auth-dialog').addEventListener('close', () => {
    if (getElement('auth-dialog').open) return;
    cancelAuthRequest();
    getElement('auth-form').reset();
    getElement('auth-status').textContent = '';
  });
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
    if (pendingAuth) return;
    setAuthMode(button.dataset.tab === 'signup');
  }));
  getElement('auth-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (pendingAuth) return;
    const isSignup = signup;
    const id = getElement('auth-name').value.trim();
    const password = getElement('auth-password').value;
    const status = getElement('auth-status');

    const idLength = Array.from(id).length;
    if (!idLength || idLength > 50 || (isSignup && idLength < 3)) {
      status.textContent = isSignup ? '아이디는 3~50자로 입력해 주세요.' : '아이디는 1~50자로 입력해 주세요.';
      return;
    }
    if (!password.trim() || new TextEncoder().encode(password).length > 72 || (isSignup && Array.from(password).length < 8)) {
      status.textContent = isSignup ? '비밀번호는 8자 이상, UTF-8 기준 72바이트 이내로 입력해 주세요.'
        : '비밀번호를 공백만으로 입력할 수 없으며, UTF-8 기준 72바이트 이내여야 합니다.';
      return;
    }
    if (isSignup && password !== getElement('auth-confirm').value) {
      status.textContent = '비밀번호가 서로 다릅니다.';
      return;
    }

    const request = { controller: new AbortController(), token: getAccessToken() };
    pendingAuth = request;
    setAuthBusy(true);
    status.textContent = isSignup ? '회원가입 중입니다…' : '로그인 중입니다…';

    try {
      const result = await requestAuthentication(isSignup, id, password, request.controller.signal);
      if (pendingAuth !== request || !getElement('auth-dialog').open || request.token !== getAccessToken()) return;
      if (isSignup) {
        status.textContent = '회원가입이 완료되었습니다. 로그인해 주세요.';
        getElement('auth-password').value = '';
        getElement('auth-confirm').value = '';
      } else {
        if (!getAuthenticatedId(result.token)) throw new Error('유효한 로그인 정보를 받지 못했습니다. 다시 시도해 주세요.');
        try {
          localStorage.setItem('access_token', result.token);
          rejectedToken = null;
        } catch (_) {
          status.textContent = '로그인 정보를 저장하지 못했습니다. 브라우저 저장소 설정을 확인해 주세요.';
          return;
        }
        getElement('auth-form').reset();
        getElement('auth-dialog').close();
        syncAuthState('login');
      }
    } catch (error) {
      if (pendingAuth === request && getElement('auth-dialog').open && request.token === getAccessToken() && error.name !== 'AbortError') {
        status.textContent = error.message || '인증 요청에 실패했습니다.';
      }
    } finally {
      if (pendingAuth === request) {
        pendingAuth = null;
        setAuthBusy(false);
      }
    }
  });
}

syncAuthState();
bindAuthEvents();
window.addEventListener('storage', event => {
  if (event.storageArea && event.storageArea !== localStorage) return;
  if (event.key !== 'access_token' && event.key !== null) return;
  syncAuthState('storage');
});
window.addEventListener('focus', () => syncAuthState());
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) syncAuthState();
});
