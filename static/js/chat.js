import { getAccessToken, getAuthenticatedId, clearAuth, openLogin } from './auth.js';
import { requestReply } from './chat-api.js';

const MAX_QUESTION_LENGTH = 5000;
const MAX_CHATS = 30;
const elements = new Map();

function getElement(id) {
  if (!elements.has(id)) elements.set(id, document.getElementById(id));
  return elements.get(id);
}
const brand = '담다';
const guestStorageKey = 'damda-chat-v1';
const storageKeyFor = id => id ? `${guestStorageKey}:user:${encodeURIComponent(id)}` : guestStorageKey;
let ownerId = getAuthenticatedId();
let storageKey = storageKeyFor(ownerId);
let draft = null;
let chats = [];
let activeId = null;
let pending = null;
let retryRoom = null;
let toastTimer;
// 공개 HTTP 주소에서도 방 ID를 만들 수 있게 secure context 전용 UUID API를 보완한다.
const uid = () => crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');

// 브라우저 안에서 게스트와 각 로그인 ID의 대화를 따로 저장합니다.
function loadChats() {
  try {
    const loaded = JSON.parse(localStorage.getItem(storageKey) || '[]');
    return Array.isArray(loaded) ? loaded.filter(isValidChat).slice(0, MAX_CHATS).map(chat => {
      // 이전 slice(0, 30)으로 잘린 이모지 제목은 UTF-8 저장이 가능하도록 복원한다.
      const wellFormed = text => Array.from(text, character =>
        character.length === 1 && character >= '\uD800' && character <= '\uDFFF' ? '\uFFFD' : character).join('');
      if (!chat.title.trim() || Array.from(chat.title).length > 100 || wellFormed(chat.title) !== chat.title) {
        const firstQuestion = chat.messages.find(message => message.role === 'user')?.text || '새로운 대화';
        chat.title = Array.from(wellFormed(firstQuestion)).slice(0, 30).join('');
      }
      return chat;
    }) : [];
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
    return true;
  } catch (_) {
    toast('저장하지 못했습니다. 새로고침하면 이전 기록이 다시 나타나거나 이번 변경이 사라질 수 있습니다.');
    return false;
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
      retryRoom = null;
      setStatus();
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
      retryRoom = null;
      setStatus();
      const saved = save();
      renderHistory();
      renderChat();
      if (saved) toast('이 브라우저에서 대화를 삭제했습니다.');
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
  if (!ownerId && draft) draft.question = getElement('question').value;
  if (retryRoom && getElement('question').value.trim() !== retryRoom.question) getElement('retry').hidden = true;
  const count = Array.from(getElement('question').value).length;
  getElement('char-count').textContent = count.toLocaleString() + ' / ' + MAX_QUESTION_LENGTH.toLocaleString();
  getElement('question').style.height = 'auto';
  getElement('question').style.height = Math.min(getElement('question').scrollHeight, 150) + 'px';
}

function newChat() {
  if (pending) return;
  if (!ownerId) draft = null;
  activeId = null;
  retryRoom = null;
  getElement('question').value = '';
  setStatus();
  updateInput();
  renderChat();
  renderHistory();
  setDrawer(false);
  getElement('question').focus();
}

function setStatus(message = '', type = 'info', { requestId = null, retry = false, login = false } = {}) {
  const status = getElement('status');
  status.dataset.state = type;
  status.setAttribute('role', type === 'error' ? 'alert' : 'status');
  status.textContent = message;
  getElement('question').removeAttribute('aria-invalid');
  getElement('request-id').textContent = requestId ? `요청 ID: ${requestId}` : '';
  getElement('request-id').hidden = !requestId;
  getElement('retry').hidden = !retry;
  getElement('reauth').hidden = !login;
}

function setBusy(value) {
  getElement('send').hidden = value;
  getElement('stop').hidden = !value;
  getElement('question').disabled = value;
  getElement('chat-form').setAttribute('aria-busy', String(value));
  getElement('transcript').setAttribute('aria-busy', String(value));
  getElement('retry').disabled = value;
  document.querySelectorAll('[data-new], [data-prompt], .history-item, .delete-chat').forEach(b => b.disabled = value);
}

function switchChatOwner(id, reason) {
  const nextStorageKey = storageKeyFor(id);
  if (nextStorageKey === storageKey) return;
  const preserveDraft = ownerId && !id && ['expired', 'unauthorized'].includes(reason);
  if (preserveDraft) {
    draft = { id: ownerId, question: getElement('question').value, activeId };
  } else if (id !== draft?.id) {
    draft = null;
  }
  pending?.abort();
  pending = null;
  retryRoom = null;
  storageKey = nextStorageKey;
  ownerId = id;
  chats = loadChats();
  const restoreDraft = id && draft?.id === id;
  activeId = restoreDraft && chats.some(chat => chat.id === draft.activeId) ? draft.activeId : null;
  getElement('question').value = preserveDraft || restoreDraft ? draft.question : '';
  if (restoreDraft) draft = null;
  getElement('history-search').value = '';
  setStatus();
  if (preserveDraft) setStatus('로그인이 만료됐습니다. 같은 계정으로 다시 로그인하면 질문을 이어서 보낼 수 있습니다.', 'error');
  setBusy(false);
  updateInput();
  renderHistory();
  renderChat();
}

// 질문 전송과 취소, 실패 시 대화 복원을 처리합니다.
async function handleSubmit(event) {
  event.preventDefault();
  if (pending) return;
  if (!getAuthenticatedId()) {
    clearAuth();
    setStatus('로그인 후 질문을 보내 주세요.', 'error', { login: true });
    return;
  }
  const question = getElement('question').value.trim();
  if (!question) {
    setStatus('메시지를 입력해 주세요.', 'error');
    return;
  }
  if (Array.from(question).length > MAX_QUESTION_LENGTH) {
    setStatus('메시지는 5,000자 이내로 입력해 주세요.', 'error');
    return;
  }
  let current = chats.find(c => c.id === activeId);
  const previousChats = chats.slice();
  const isNewChat = !current;
  if (!current) {
    current = {
      id: retryRoom?.id || uid(),
      title: retryRoom?.title || Array.from(question).slice(0, 30).join(''),
      messages: []
    };
    chats.unshift(current);
    chats = chats.slice(0, MAX_CHATS);
    activeId = current.id;
  }
  const controller = new AbortController();
  const token = getAccessToken();
  const requestStorageKey = storageKey;
  pending = controller;
  current.messages.push({
    role: 'user',
    text: question
  });
  renderChat();
  renderHistory();
  setBusy(true);
  setStatus('답변을 기다리고 있어요…', 'loading');
  try {
    const reply = await requestReply(question, current.id, current.title, token, controller.signal);
    if (pending !== controller || storageKey !== requestStorageKey) return;
    current.messages.push({
      role: 'assistant',
      text: reply
    });
    getElement('question').value = '';
    retryRoom = null;
    setStatus();
    save();
  } catch (error) {
    if (pending !== controller || storageKey !== requestStorageKey) return;
    current.messages.pop();
    if (isNewChat) {
      chats = previousChats;
      activeId = null;
    }
    const cancelled = error.name === 'AbortError';
    // 코드가 없는 프록시 오류에만 HTTP 상태를 보조 기준으로 사용한다.
    const code = error.errorCode || ({ 401: 'UNAUTHORIZED', 422: 'INVALID_INPUT', 429: 'AI_RATE_LIMIT', 504: 'AI_TIMEOUT' })[error.status];
    const unauthorized = code === 'UNAUTHORIZED' || error.status === 401;
    if (unauthorized) clearAuth(token);
    else retryRoom = { id: current.id, title: current.title, question };
    setStatus(
      cancelled ? '응답 대기를 중지했어요. 입력한 질문은 남겨두었습니다.'
        : (error.message || '응답을 받지 못했어요. 다시 시도해 주세요.'),
      cancelled ? 'info' : 'error',
      { requestId: error.requestId, retry: !unauthorized && ['AI_TIMEOUT', 'CLIENT_TIMEOUT'].includes(code), login: unauthorized && !getAuthenticatedId() }
    );
    if (unauthorized && !getAuthenticatedId()) openLogin();
    if (code === 'INVALID_INPUT') getElement('question').setAttribute('aria-invalid', 'true');
  } finally {
    if (pending === controller) {
      pending = null;
      setBusy(false);
      renderChat();
      renderHistory();
      updateInput();
      if (!getElement('auth-dialog').open) getElement('question').focus();
    }
  }
}

// 채팅 이벤트 연결
function bindChatEvents() {
  getElement('chat-form').addEventListener('submit', handleSubmit);
  getElement('stop').addEventListener('click', () => pending?.abort());
  getElement('retry').addEventListener('click', () => getElement('chat-form').requestSubmit());
  getElement('reauth').addEventListener('click', openLogin);
  getElement('question').addEventListener('input', () => {
    getElement('question').removeAttribute('aria-invalid');
    updateInput();
  });
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

chats = loadChats();
window.addEventListener('authchange', event => switchChatOwner(event.detail.id, event.detail.reason));
bindChatEvents();
updateInput();
renderHistory();
renderChat();
