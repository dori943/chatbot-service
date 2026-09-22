const elements = new Map();

export function getAuthenticatedId() {
  try {
    const payload = localStorage.getItem('access_token')?.split('.')[1];
    if (!payload) return null;
    const claims = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof claims.id === 'string' && claims.id ? claims.id : null;
  } catch (_) {
    return null;
  }
}

function getElement(id) {
  if (!elements.has(id)) elements.set(id, document.getElementById(id));
  return elements.get(id);
}

let signup = false;

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

function notifyAuthChange() {
  window.dispatchEvent(new CustomEvent('authchange', { detail: { id: getAuthenticatedId() } }));
}

// 인증 모달의 입력과 탭 전환을 처리합니다.
function bindAuthEvents() {
  document.querySelectorAll('[data-auth]').forEach(button => button.addEventListener('click', () => {
    if (getAuthenticatedId()) {
      localStorage.removeItem('access_token');
      renderAuthUI();
      notifyAuthChange();
      return;
    }
    getElement('auth-status').textContent = '';
    getElement('auth-dialog').showModal();
    getElement('auth-name').focus();
  }));
  document.querySelector('[data-close]').addEventListener('click', () => getElement('auth-dialog').close());
  getElement('auth-dialog').addEventListener('close', () => {
    getElement('auth-form').reset();
    getElement('auth-status').textContent = '';
  });
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
    signup = button.dataset.tab === 'signup';
    document.querySelectorAll('[data-tab]').forEach(tab => tab.classList.toggle('active', tab === button));
    getElement('auth-title').textContent = signup ? '새로운 대화를 시작해요.' : '다시 만나 반가워요.';
    getElement('confirm-wrap').hidden = !signup;
    getElement('auth-confirm').required = signup;
    getElement('auth-password').autocomplete = signup ? 'new-password' : 'current-password';
    document.querySelector('.auth-submit').textContent = signup ? '회원가입' : '로그인';
    getElement('auth-status').textContent = '';
  }));
  getElement('auth-form').addEventListener('submit', async event => {
    event.preventDefault();
    const id = getElement('auth-name').value;
    const password = getElement('auth-password').value;
    const status = getElement('auth-status');

    if (signup && password !== getElement('auth-confirm').value) {
      status.textContent = '비밀번호가 서로 다릅니다.';
      return;
    }

    const endpoint = signup ? '/auth/register' : '/auth/login';

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, pw: password })
      });
      const result = await response.json();

      if (!response.ok) {
        status.textContent = '요청에 실패했습니다.';
        return;
      }

      if (signup) {
        status.textContent = result.message;
        getElement('auth-password').value = '';
        getElement('auth-confirm').value = '';
      } else if (typeof result.token === 'string' && result.token) {
        localStorage.setItem('access_token', result.token);
        getElement('auth-form').reset();
        getElement('auth-dialog').close();
        renderAuthUI();
        notifyAuthChange();
      } else {
        status.textContent = result.message || '로그인에 실패했습니다.';
      }
    } catch (error) {
      status.textContent = '서버 연결에 실패했습니다.';
    }
  });
}

renderAuthUI();
bindAuthEvents();
window.addEventListener('storage', event => {
  if (event.key !== 'access_token') return;
  renderAuthUI();
  notifyAuthChange();
});
