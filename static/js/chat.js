import {
  requestReply
} from './api.js';

const MAX_QUESTION_LENGTH = 1000;
const MAX_CHATS = 30;
const elements = new Map();

function getElement(id) {
  if (!elements.has(id)) elements.set(id, document.getElementById(id));
  return elements.get(id);
}
const brand = '담다';
const storageKey = 'damda-chat-v1';
let chats = [];
let activeId = null;
let pending = null;
let toastTimer;
let signup = false;
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

// 로컬 기록 읽기/쓰기 (사용자별 서버 기록 연동은 별도 작업)
function loadChats() {
  try {
    const loaded = JSON.parse(localStorage.getItem(storageKey) || '[]');
    return Array.isArray(loaded) ? loaded.filter(isValidChat).slice(0, MAX_CHATS) : [];
  } catch (_) {
    return [];
  }
}

function isValidChat(chat) {
  return chat && typeof chat.id === 'string' && typeof chat.title === 'string' &&
    Array.isArray(chat.messages) && chat.messages.every(message =>
      message && ['user', 'assistant'].includes(message.role) && typeof message.text === 'string');
}

function save() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(chats.slice(0, MAX_CHATS)));
  } catch (_) {
    toast('브라우저 저장 공간을 사용할 수 없어 이번 화면에서만 유지됩니다.');
  }
}

function toast(text) {
  clearTimeout(toastTimer);
  getElement('toast').textContent = text;
  getElement('toast').hidden = false;
  toastTimer = setTimeout(() => {
    getElement('toast').hidden = true;
  }, 3000);
}

function setDrawer(open) {
  getElement('sidebar').classList.toggle('is-open', open);
  getElement('scrim').hidden = !open;
  getElement('menu').setAttribute('aria-expanded', String(open));
  if (open) getElement('history-search').focus();
}

function renderHistory() {
  const query = getElement('history-search').value.trim().toLowerCase();
  getElement('history-list').replaceChildren();
  const visible = chats.filter(c => c.title.toLowerCase().includes(query));
  visible.forEach(c => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-item' + (c.id === activeId ? ' active' : '');
    button.textContent = c.title;
    button.title = c.title;
    button.disabled = !!pending;
    button.addEventListener('click', () => {
      if (pending) return;
      activeId = c.id;
      renderChat();
      renderHistory();
      setDrawer(false);
    });
    getElement('history-list').append(button);
  });
  getElement('history-count').textContent = chats.length;
  getElement('history-empty').hidden = visible.length > 0;
  getElement('history-empty').textContent = query ? '검색 결과가 없습니다.' : '아직 대화가 없습니다. 첫 질문을 남겨보세요.';
}
async function copyText(text, parent) {
  try {
    if (!navigator.clipboard) throw new Error('fallback');
    await navigator.clipboard.writeText(text);
    toast('답변을 복사했습니다.');
  } catch (_) {
    let area = parent.querySelector('.fallback-copy');
    if (!area) {
      area = document.createElement('textarea');
      area.readOnly = true;
      area.className = 'fallback-copy';
      area.setAttribute('aria-label', '복사할 답변');
      parent.append(area);
    }
    area.value = text;
    area.focus();
    area.select();
    toast('텍스트를 선택했습니다. ⌘C 또는 Ctrl+C로 복사하세요.');
  }
}

// 선택한 대화의 메시지와 작업 버튼을 표시합니다.
function renderChat() {
  const current = chats.find(c => c.id === activeId);
  const messages = current?.messages || [];
  getElement('welcome').hidden = messages.length > 0;
  getElement('transcript').hidden = !messages.length;
  getElement('conversation-title').textContent = current?.title || '새로운 대화';
  getElement('transcript').replaceChildren();
  if (messages.length) {
    const tools = document.createElement('div');
    tools.className = 'thread-tools';
    const remove = document.createElement('button');
    remove.className = 'delete-chat';
    remove.textContent = '이 대화 삭제';
    remove.type = 'button';
    remove.disabled = !!pending;
    remove.addEventListener('click', () => {
      if (pending) return;
      chats = chats.filter(c => c.id !== activeId);
      activeId = null;
      save();
      renderHistory();
      renderChat();
      toast('이 브라우저에서 대화를 삭제했습니다.');
    });
    tools.append(remove);
    getElement('transcript').append(tools);
  }
  messages.forEach(m => {
    const article = document.createElement('article');
    article.className = 'message ' + m.role;
    const meta = document.createElement('div');
    meta.className = 'message-meta';
    const name = document.createElement('b');
    name.textContent = m.role === 'user' ? '나' : brand;
    meta.append(name);
    const text = document.createElement('div');
    text.className = 'message-text';
    text.textContent = m.text;
    article.append(meta, text);
    if (m.role === 'assistant') {
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'copy-button';
      copy.textContent = '답변 복사';
      copy.addEventListener('click', () => copyText(m.text, article));
      article.append(copy);
    }
    getElement('transcript').append(article);
  });
  const pane = document.querySelector('.chat-body');
  requestAnimationFrame(() => {
    pane.scrollTop = pane.scrollHeight;
  });
}

function updateInput() {
  const count = Array.from(getElement('question').value).length;
  getElement('char-count').textContent = count.toLocaleString() + ' / ' + MAX_QUESTION_LENGTH.toLocaleString();
  getElement('question').style.height = 'auto';
  getElement('question').style.height = Math.min(getElement('question').scrollHeight, 150) + 'px';
}

function newChat() {
  if (pending) return;
  activeId = null;
  getElement('question').value = '';
  setStatus();
  updateInput();
  renderChat();
  renderHistory();
  setDrawer(false);
  getElement('question').focus();
}

function setStatus(message = '', type = 'info') {
  const status = getElement('status');
  status.dataset.state = type;
  status.setAttribute('role', type === 'error' ? 'alert' : 'status');
  status.textContent = message;
}

function setBusy(value) {
  getElement('send').hidden = value;
  getElement('stop').hidden = !value;
  getElement('question').disabled = value;
  document.querySelectorAll('[data-new], [data-prompt], .history-item, .delete-chat').forEach(b => b.disabled = value);
}

// 질문 전송과 취소, 실패 시 대화 복원을 처리합니다.
async function handleSubmit(event) {
  event.preventDefault();
  if (pending) return;
  const question = getElement('question').value.trim();
  if (!question) {
    setStatus('메시지를 입력해 주세요.', 'error');
    return;
  }
  if (Array.from(question).length > MAX_QUESTION_LENGTH) {
    setStatus('메시지는 1,000자 이내로 입력해 주세요.', 'error');
    return;
  }
  let current = chats.find(c => c.id === activeId);
  const previousChats = chats.slice();
  const isNewChat = !current;
  if (!current) {
    current = {
      id: uid(),
      title: question.slice(0, MAX_CHATS),
      messages: []
    };
    chats.unshift(current);
    chats = chats.slice(0, MAX_CHATS);
    activeId = current.id;
  }
  const controller = new AbortController();
  pending = controller;
  current.messages.push({
    role: 'user',
    text: question
  });
  renderChat();
  renderHistory();
  setBusy(true);
  setStatus('답변을 기다리고 있어요…');
  try {
    const reply = await requestReply(question, controller.signal);
    current.messages.push({
      role: 'assistant',
      text: reply
    });
    getElement('question').value = '';
    setStatus();
    save();
  } catch (error) {
    current.messages.pop();
    if (isNewChat) {
      chats = previousChats;
      activeId = null;
    }
    const cancelled = error.name === 'AbortError';
    setStatus(
      cancelled ? '응답 대기를 중지했어요. 입력한 질문은 남겨두었습니다.'
        : (error.message || '응답을 받지 못했어요. 다시 시도해 주세요.'),
      cancelled ? 'info' : 'error'
    );
  } finally {
    pending = null;
    setBusy(false);
    renderChat();
    renderHistory();
    updateInput();
    getElement('question').focus();
  }
}

// 채팅 이벤트 연결
function bindChatEvents() {
  getElement('chat-form').addEventListener('submit', handleSubmit);
  getElement('stop').addEventListener('click', () => pending?.abort());
  getElement('question').addEventListener('input', updateInput);
  getElement('question').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      getElement('chat-form').requestSubmit();
    }
  });
  document.querySelectorAll('[data-new]').forEach(b => b.addEventListener('click', newChat));
  document.querySelectorAll('[data-prompt]').forEach(b => b.addEventListener('click', () => {
    if (pending) return;
    getElement('question').value = b.dataset.prompt;
    updateInput();
    getElement('question').focus();
  }));
  getElement('history-search').addEventListener('input', renderHistory);
  getElement('menu').addEventListener('click', () => setDrawer(!getElement('sidebar').classList.contains('is-open')));
  getElement('close-history')?.addEventListener('click', () => setDrawer(false));
  getElement('scrim').addEventListener('click', () => setDrawer(false));
  document.querySelector('[data-focus-search]')?.addEventListener('click', () => getElement('history-search').focus());
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') setDrawer(false);
  });

}

// 인증 모달의 입력과 탭 전환을 처리합니다.
function bindAuthEvents() {
  document.querySelectorAll('[data-auth]').forEach(b => b.addEventListener('click', () => {
    getElement('auth-status').textContent = '';
    getElement('auth-dialog').showModal();
    getElement('auth-name').focus();
  }));
  document.querySelector('[data-close]').addEventListener('click', () => getElement('auth-dialog').close());
  getElement('auth-dialog').addEventListener('close', () => {
    getElement('auth-form').reset();
    getElement('auth-status').textContent = '';
  });
  document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
    signup = b.dataset.tab === 'signup';
    document.querySelectorAll('[data-tab]').forEach(t => t.classList.toggle('active', t === b));
    getElement('auth-title').textContent = signup ? '새로운 대화를 시작해요.' : '다시 만나 반가워요.';
    getElement('confirm-wrap').hidden = !signup;
    getElement('auth-confirm').required = signup;
    getElement('auth-password').autocomplete = signup ? 'new-password' : 'current-password';
    document.querySelector('.auth-submit').textContent = signup ? '회원가입 화면 확인' : '로그인 화면 확인';
    getElement('auth-status').textContent = '';
  }));
  getElement('auth-form').addEventListener('submit', event => {
    event.preventDefault();
    if (signup && getElement('auth-password').value !== getElement('auth-confirm').value) {
      getElement('auth-status').textContent = '비밀번호가 서로 다릅니다.';
      return;
    }
    getElement('auth-status').textContent = '입력 확인 완료! 실제 ' + (signup ? '회원가입' : '로그인') + '은 백엔드 연결 후 사용할 수 있어요.';
    getElement('auth-password').value = '';
    getElement('auth-confirm').value = '';
  });
}

chats = loadChats();
bindChatEvents();
bindAuthEvents();
updateInput();
renderHistory();
renderChat();
