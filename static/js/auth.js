const elements = new Map();

function getElement(id) {
  if (!elements.has(id)) elements.set(id, document.getElementById(id));
  return elements.get(id);
}

let signup = false;

// 인증 모달의 입력과 탭 전환을 처리합니다.
function bindAuthEvents() {
  document.querySelectorAll('[data-auth]').forEach(button => button.addEventListener('click', () => {
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
      } else if (typeof result.token === 'string' && result.token) {
        localStorage.setItem('access_token', result.token);
        status.textContent = result.message;
      } else {
        status.textContent = result.message || '로그인에 실패했습니다.';
      }
    } catch (error) {
      status.textContent = '서버 연결에 실패했습니다.';
    }
  });
}

bindAuthEvents();
