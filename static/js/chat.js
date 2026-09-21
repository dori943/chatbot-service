import { requestReply } from './api.js';

/* 채팅 화면의 이벤트와 렌더링을 담당합니다.
   실제 AI·회원 서버와 연결되지 않은 UI 예시이며, 대화만 이 브라우저에 저장합니다. */
'use strict';
const $ = (id) => document.getElementById(id);
const design = document.body.dataset.design;
const brand = {
  damda: '담다',
  orbit: 'ORBIT',
  yeobaek: '여백'
} [design];
const storageKey = 'llm-front-example-v1-' + design;
let chats = [];
let hasSavedChats = false;
let activeId = null;
let pending = null;
let toastTimer;
let signup = false;
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

// 저장소 사용이 제한된 브라우저에서는 메모리에서만 동작합니다.
try {
  const loaded = JSON.parse(localStorage.getItem(storageKey) || 'null');
  if (Array.isArray(loaded)) {
    hasSavedChats = true;
    chats = loaded.filter(c => c && typeof c.id === 'string' && typeof c.title === 'string' && Array.isArray(c.messages) && c.messages.every(m => m && ['user', 'assistant'].includes(m.role) && typeof m.text === 'string')).slice(0, 30);
  }
} catch (_) {
  chats = [];
}
if (!hasSavedChats) {
  chats = [{
    id: uid(),
    title: '프로젝트 아이디어 정리',
    messages: [{
      role: 'user',
      text: '작은 팀이 만들기 좋은 프로젝트 아이디어가 있을까?'
    }, {
      role: 'assistant',
      text: '[미리보기 예시]\n일상의 작은 불편에서 출발해 보세요.\n\n1. 팀 일정과 할 일을 정리하는 도구\n2. 읽은 책과 메모를 모아두는 공간\n3. 질문과 답변을 저장하는 AI 챗봇\n\n첫 버전은 가장 중요한 기능 하나에 집중하면 좋아요.'
    }]
  }, {
    id: uid(),
    title: '주말 여행 계획 세우기',
    messages: [{
      role: 'user',
      text: '하루를 여유롭게 보내는 여행 계획을 세워줘.'
    }, {
      role: 'assistant',
      text: '[미리보기 예시]\n오전에는 산책, 점심에는 가보고 싶었던 식당, 오후에는 카페나 전시를 한 곳 골라보세요. 이동을 줄이면 더 편안하게 즐길 수 있어요.'
    }]
  }, {
    id: uid(),
    title: '글의 핵심을 간결하게',
    messages: [{
      role: 'user',
      text: '글을 짧게 정리하는 방법을 알려줘.'
    }, {
      role: 'assistant',
      text: '[미리보기 예시]\n가장 전하고 싶은 내용을 한 문장으로 먼저 써보세요. 그 문장을 설명하는 근거만 남기고, 같은 뜻의 표현은 하나로 합쳐보세요.'
    }]
  }];
}

function save() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(chats.slice(0, 30)));
  } catch (_) {
    toast('브라우저 저장 공간을 사용할 수 없어 이번 화면에서만 유지됩니다.');
  }
}

function toast(text) {
  clearTimeout(toastTimer);
  $('toast').textContent = text;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => {
    $('toast').hidden = true;
  }, 3000);
}

function setDrawer(open) {
  $('sidebar').classList.toggle('is-open', open);
  $('scrim').hidden = !open;
  $('menu').setAttribute('aria-expanded', String(open));
  if (open) $('history-search').focus();
}

function renderHistory() {
  const query = $('history-search').value.trim().toLowerCase();
  $('history-list').replaceChildren();
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
    $('history-list').append(button);
  });
  $('history-count').textContent = chats.length;
  $('history-empty').hidden = visible.length > 0;
  $('history-empty').textContent = query ? '검색 결과가 없습니다.' : '아직 대화가 없습니다. 첫 질문을 남겨보세요.';
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

function renderChat() {
  const current = chats.find(c => c.id === activeId);
  const messages = current?.messages || [];
  $('welcome').hidden = messages.length > 0;
  $('transcript').hidden = !messages.length;
  $('conversation-title').textContent = current?.title || '새로운 대화';
  $('transcript').replaceChildren();
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
    $('transcript').append(tools);
  }
  messages.forEach(m => {
    const article = document.createElement('article');
    article.className = 'message ' + m.role;
    const meta = document.createElement('div');
    meta.className = 'message-meta';
    const name = document.createElement('b');
    name.textContent = m.role === 'user' ? '나' : brand;
    meta.append(name);
    if (m.role === 'assistant') {
      const tag = document.createElement('span');
      tag.textContent = '예시 응답';
      meta.append(tag);
    }
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
    $('transcript').append(article);
  });
  const pane = document.querySelector('.chat-body');
  requestAnimationFrame(() => {
    pane.scrollTop = pane.scrollHeight;
  });
}

function updateInput() {
  const count = Array.from($('question').value).length;
  $('char-count').textContent = count.toLocaleString() + ' / 1,000';
  $('question').style.height = 'auto';
  $('question').style.height = Math.min($('question').scrollHeight, 150) + 'px';
}

function newChat() {
  if (pending) return;
  activeId = null;
  $('question').value = '';
  $('status').textContent = '';
  updateInput();
  renderChat();
  renderHistory();
  setDrawer(false);
  $('question').focus();
}

function setBusy(value) {
  $('send').hidden = value;
  $('stop').hidden = !value;
  $('question').disabled = value;
  document.querySelectorAll('[data-new], [data-prompt], .history-item, .delete-chat').forEach(b => b.disabled = value);
}

$('chat-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (pending) return;
  const question = $('question').value.trim();
  if (!question) {
    $('status').textContent = '메시지를 입력해 주세요.';
    return;
  }
  if (Array.from(question).length > 1000) {
    $('status').textContent = '메시지는 1,000자 이내로 입력해 주세요.';
    return;
  }
  let current = chats.find(c => c.id === activeId);
  const previousChats = chats.slice();
  const isNewChat = !current;
  if (!current) {
    current = {
      id: uid(),
      title: question.slice(0, 30),
      messages: []
    };
    chats.unshift(current);
    chats = chats.slice(0, 30);
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
  $('status').textContent = '답변 화면을 준비하고 있어요…';
  try {
    const reply = await requestReply(question, controller.signal);
    current.messages.push({
      role: 'assistant',
      text: reply
    });
    $('question').value = '';
    $('status').textContent = '';
    save();
  } catch (error) {
    current.messages.pop();
    if (isNewChat) {
      chats = previousChats;
      activeId = null;
    }
    $('status').textContent = error.name === 'AbortError' ? '응답을 중지했어요. 입력한 질문은 남겨두었습니다.' : '응답을 받지 못했어요. 다시 시도해 주세요.';
  } finally {
    pending = null;
    setBusy(false);
    renderChat();
    renderHistory();
    updateInput();
    $('question').focus();
  }
});
$('stop').addEventListener('click', () => pending?.abort());
$('question').addEventListener('input', updateInput);
$('question').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('chat-form').requestSubmit();
  }
});
document.querySelectorAll('[data-new]').forEach(b => b.addEventListener('click', newChat));
document.querySelectorAll('[data-prompt]').forEach(b => b.addEventListener('click', () => {
  if (pending) return;
  $('question').value = b.dataset.prompt;
  updateInput();
  $('question').focus();
}));
$('history-search').addEventListener('input', renderHistory);
$('menu').addEventListener('click', () => setDrawer(!$('sidebar').classList.contains('is-open')));
$('close-history')?.addEventListener('click', () => setDrawer(false));
$('scrim').addEventListener('click', () => setDrawer(false));
document.querySelector('[data-focus-search]')?.addEventListener('click', () => $('history-search').focus());
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') setDrawer(false);
});

// 로그인과 회원가입은 UI만 확인합니다. 비밀번호는 어디에도 저장하지 않습니다.
document.querySelectorAll('[data-auth]').forEach(b => b.addEventListener('click', () => {
  $('auth-status').textContent = '';
  $('auth-dialog').showModal();
  $('auth-name').focus();
}));
document.querySelector('[data-close]').addEventListener('click', () => $('auth-dialog').close());
$('auth-dialog').addEventListener('close', () => {
  $('auth-form').reset();
  $('auth-status').textContent = '';
});
document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => {
  signup = b.dataset.tab === 'signup';
  document.querySelectorAll('[data-tab]').forEach(t => t.classList.toggle('active', t === b));
  $('auth-title').textContent = signup ? '새로운 대화를 시작해요.' : '다시 만나 반가워요.';
  $('confirm-wrap').hidden = !signup;
  $('auth-confirm').required = signup;
  $('auth-password').autocomplete = signup ? 'new-password' : 'current-password';
  document.querySelector('.auth-submit').textContent = signup ? '회원가입 화면 확인' : '로그인 화면 확인';
  $('auth-status').textContent = '';
}));
$('auth-form').addEventListener('submit', event => {
  event.preventDefault();
  if (signup && $('auth-password').value !== $('auth-confirm').value) {
    $('auth-status').textContent = '비밀번호가 서로 다릅니다.';
    return;
  }
  $('auth-status').textContent = '입력 확인 완료! 실제 ' + (signup ? '회원가입' : '로그인') + '은 백엔드 연결 후 사용할 수 있어요.';
  $('auth-password').value = '';
  $('auth-confirm').value = '';
});
renderHistory();
renderChat();
