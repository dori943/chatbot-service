/* 세 디자인이 공유하는 프론트 동작입니다. 프레임워크나 빌드 도구 없이 실행됩니다.
   실제 AI·회원 서버와 연결되지 않은 UI 예시이며, 대화만 이 브라우저에 저장합니다. */
'use strict';
const $ = (id) => document.getElementById(id);
const design = document.body.dataset.design;
const brand = {damda:'담다',orbit:'ORBIT',yeobaek:'여백'}[design];
const storageKey = 'llm-front-example-v1-' + design;
let chats = [];
let hasSavedChats = false;
let activeId = null;
let pending = null;
let toastTimer;
let signup = false;
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2,8);

// 저장소 사용이 제한된 브라우저에서는 메모리에서만 동작합니다.
try {
  const loaded = JSON.parse(localStorage.getItem(storageKey) || 'null');
  if (Array.isArray(loaded)) { hasSavedChats = true; chats = loaded.filter(c => c && typeof c.id === 'string' && typeof c.title === 'string' && Array.isArray(c.messages) && c.messages.every(m => m && ['user','assistant'].includes(m.role) && typeof m.text === 'string')).slice(0,30); }
} catch (_) { chats = []; }
if (!hasSavedChats) {
  chats = [
    {id:uid(),title:'프로젝트 아이디어 정리',messages:[{role:'user',text:'작은 팀이 만들기 좋은 프로젝트 아이디어가 있을까?'},{role:'assistant',text:'[미리보기 예시]\n일상의 작은 불편에서 출발해 보세요.\n\n1. 팀 일정과 할 일을 정리하는 도구\n2. 읽은 책과 메모를 모아두는 공간\n3. 질문과 답변을 저장하는 AI 챗봇\n\n첫 버전은 가장 중요한 기능 하나에 집중하면 좋아요.'}]},
    {id:uid(),title:'주말 여행 계획 세우기',messages:[{role:'user',text:'하루를 여유롭게 보내는 여행 계획을 세워줘.'},{role:'assistant',text:'[미리보기 예시]\n오전에는 산책, 점심에는 가보고 싶었던 식당, 오후에는 카페나 전시를 한 곳 골라보세요. 이동을 줄이면 더 편안하게 즐길 수 있어요.'}]},
    {id:uid(),title:'글의 핵심을 간결하게',messages:[{role:'user',text:'글을 짧게 정리하는 방법을 알려줘.'},{role:'assistant',text:'[미리보기 예시]\n가장 전하고 싶은 내용을 한 문장으로 먼저 써보세요. 그 문장을 설명하는 근거만 남기고, 같은 뜻의 표현은 하나로 합쳐보세요.'}]}
  ];
}
function save() {
  try { localStorage.setItem(storageKey, JSON.stringify(chats.slice(0,30))); }
  catch (_) { toast('브라우저 저장 공간을 사용할 수 없어 이번 화면에서만 유지됩니다.'); }
}
function toast(text) {
  clearTimeout(toastTimer); $('toast').textContent=text; $('toast').hidden=false;
  toastTimer=setTimeout(()=>{$('toast').hidden=true;},3000);
}
function setDrawer(open) {
  $('sidebar').classList.toggle('is-open',open);
  $('scrim').hidden=!open;
  $('menu').setAttribute('aria-expanded',String(open));
  if (open) $('history-search').focus();
}
function renderHistory() {
  const query=$('history-search').value.trim().toLowerCase();
  $('history-list').replaceChildren();
  const visible=chats.filter(c=>c.title.toLowerCase().includes(query));
  visible.forEach(c=>{
    const button=document.createElement('button');button.type='button';
    button.className='history-item'+(c.id===activeId?' active':'');
    button.textContent=c.title;button.title=c.title;button.disabled=!!pending;
    button.addEventListener('click',()=>{if(pending)return;activeId=c.id;renderChat();renderHistory();setDrawer(false);});
    $('history-list').append(button);
  });
  $('history-count').textContent=chats.length;
  $('history-empty').hidden=visible.length>0;
  $('history-empty').textContent=query?'검색 결과가 없습니다.':'아직 대화가 없습니다. 첫 질문을 남겨보세요.';
}
async function copyText(text, parent) {
  try {
    if (!navigator.clipboard) throw new Error('fallback');
    await navigator.clipboard.writeText(text);toast('답변을 복사했습니다.');
  } catch (_) {
    let area=parent.querySelector('.fallback-copy');
    if(!area){area=document.createElement('textarea');area.readOnly=true;area.className='fallback-copy';area.setAttribute('aria-label','복사할 답변');parent.append(area);}
    area.value=text;area.focus();area.select();toast('텍스트를 선택했습니다. ⌘C 또는 Ctrl+C로 복사하세요.');
  }
}
function renderChat() {
  const current=chats.find(c=>c.id===activeId);
  const messages=current?.messages || [];
  $('welcome').hidden=messages.length>0;$('transcript').hidden=!messages.length;
  $('conversation-title').textContent=current?.title || '새로운 대화';
  $('transcript').replaceChildren();
  if (messages.length) {
    const tools=document.createElement('div');tools.className='thread-tools';
    const remove=document.createElement('button');remove.className='delete-chat';remove.textContent='이 대화 삭제';remove.type='button';remove.disabled=!!pending;
    remove.addEventListener('click',()=>{
      if(pending)return;
      chats=chats.filter(c=>c.id!==activeId);activeId=null;save();renderHistory();renderChat();toast('이 브라우저에서 대화를 삭제했습니다.');
    });tools.append(remove);$('transcript').append(tools);
  }
  messages.forEach(m=>{
    const article=document.createElement('article');article.className='message '+m.role;
    const meta=document.createElement('div');meta.className='message-meta';
    const name=document.createElement('b');name.textContent=m.role==='user'?'나':brand;
    meta.append(name);
    if(m.role==='assistant'){const tag=document.createElement('span');tag.textContent='예시 응답';meta.append(tag);}
    const text=document.createElement('div');text.className='message-text';text.textContent=m.text;
    article.append(meta,text);
    if(m.role==='assistant'){
      const copy=document.createElement('button');copy.type='button';copy.className='copy-button';copy.textContent='답변 복사';
      copy.addEventListener('click',()=>copyText(m.text,article));article.append(copy);
    }
    $('transcript').append(article);
  });
  const pane=document.querySelector('.chat-body');requestAnimationFrame(()=>{pane.scrollTop=pane.scrollHeight;});
}
function updateInput() {
  const count=Array.from($('question').value).length;
  $('char-count').textContent=count.toLocaleString()+' / 2,000';
  $('question').style.height='auto';$('question').style.height=Math.min($('question').scrollHeight,150)+'px';
}
function newChat() {
  if(pending)return;activeId=null;$('question').value='';$('status').textContent='';updateInput();renderChat();renderHistory();setDrawer(false);$('question').focus();
}
function setBusy(value) {
  $('send').hidden=value;$('stop').hidden=!value;$('question').disabled=value;
  document.querySelectorAll('[data-new], [data-prompt], .history-item, .delete-chat').forEach(b=>b.disabled=value);
}

// ★ 백엔드 연결 위치: docs/API_HANDOFF.md의 fetch 예시로 이 함수의 내부를 교체합니다.
// API 키는 이 파일에 넣지 않습니다. 지금은 네트워크 요청 없이 예시 응답만 만듭니다.
async function requestReply(message, signal) {
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(resolve,850);
    signal.addEventListener('abort',()=>{clearTimeout(timer);reject(new DOMException('중지','AbortError'));},{once:true});
  });
  if(message.includes('계획'))return '[미리보기 예시]\n일주일을 다음처럼 나누면 시작하기 편해요.\n\n월요일 — 목표와 핵심 기능 합의\n화·수요일 — 역할별 기능 구현\n목요일 — 화면과 API 연결\n금요일 — 오류 수정과 첫 배포\n\n매일 짧게 진행 상황을 공유하고, 큰 기능보다 끝낼 수 있는 작은 작업부터 진행해 보세요.\n\n실제 AI에 연결하면 질문에 맞춘 답변이 이 자리에 표시됩니다.';
  if(message.includes('리스트'))return '[미리보기 예시]\n리스트와 튜플은 여러 값을 순서대로 담습니다.\n\n리스트: [1, 2, 3] — 항목을 추가하거나 바꿀 수 있어요.\n튜플: (1, 2, 3) — 생성한 뒤 항목 자체를 바꿀 수 없어요.\n\n이 응답은 화면을 확인하기 위한 고정된 예시입니다. 실제 AI 연결은 백엔드에서 진행합니다.';
  if(message.includes('인사말'))return '[미리보기 예시]\n“안녕하세요. 오늘은 작은 아이디어가 하나의 서비스가 되기까지의 과정을 소개하려고 합니다. 저희가 어떤 문제를 발견하고, 어떻게 해결했는지 함께 살펴봐 주세요.”\n\n이런 느낌으로 대화가 표시됩니다. 실제 답변 생성은 백엔드 연결 후 사용할 수 있어요.';
  return '[미리보기 예시]\n질문을 잘 받았어요.\n\n“'+message.slice(0,180)+'”\n\n이 화면은 디자인과 사용자 흐름을 비교하는 프론트엔드 예시입니다. 질문 전송, 대화 기록, 새 대화와 복사 기능을 직접 눌러볼 수 있어요.\n\n실제 AI API에 연결하면 이 위치에 모델의 답변이 나타납니다.';
}
$('chat-form').addEventListener('submit',async event=>{
  event.preventDefault();if(pending)return;
  const question=$('question').value.trim();
  if(!question){$('status').textContent='메시지를 입력해 주세요.';return;}
  if(Array.from(question).length>2000){$('status').textContent='메시지는 2,000자 이내로 입력해 주세요.';return;}
  let current=chats.find(c=>c.id===activeId);
  if(!current){current={id:uid(),title:question.slice(0,30),messages:[]};chats.unshift(current);chats=chats.slice(0,30);activeId=current.id;}
  const controller=new AbortController();pending=controller;
  current.messages.push({role:'user',text:question});renderChat();renderHistory();setBusy(true);
  $('status').textContent='답변 화면을 준비하고 있어요…';
  try {
    const reply=await requestReply(question,controller.signal);
    current.messages.push({role:'assistant',text:reply});$('question').value='';$('status').textContent='';save();
  } catch(error) {
    current.messages.pop();$('status').textContent=error.name==='AbortError'?'응답을 중지했어요. 입력한 질문은 남겨두었습니다.':'응답을 받지 못했어요. 다시 시도해 주세요.';
  } finally {
    pending=null;setBusy(false);renderChat();renderHistory();updateInput();$('question').focus();
  }
});
$('stop').addEventListener('click',()=>pending?.abort());
$('question').addEventListener('input',updateInput);
$('question').addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('chat-form').requestSubmit();}
});
document.querySelectorAll('[data-new]').forEach(b=>b.addEventListener('click',newChat));
document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{if(pending)return;$('question').value=b.dataset.prompt;updateInput();$('question').focus();}));
$('history-search').addEventListener('input',renderHistory);
$('menu').addEventListener('click',()=>setDrawer(!$('sidebar').classList.contains('is-open')));
$('close-history')?.addEventListener('click',()=>setDrawer(false));
$('scrim').addEventListener('click',()=>setDrawer(false));
document.querySelector('[data-focus-search]')?.addEventListener('click',()=>$('history-search').focus());
document.addEventListener('keydown',event=>{if(event.key==='Escape')setDrawer(false);});

// 로그인과 회원가입은 UI만 확인합니다. 비밀번호는 어디에도 저장하지 않습니다.
document.querySelectorAll('[data-auth]').forEach(b=>b.addEventListener('click',()=>{
  $('auth-status').textContent='';$('auth-dialog').showModal();$('auth-name').focus();
}));
document.querySelector('[data-close]').addEventListener('click',()=>$('auth-dialog').close());
$('auth-dialog').addEventListener('close',()=>{$('auth-form').reset();$('auth-status').textContent='';});
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{
  signup=b.dataset.tab==='signup';document.querySelectorAll('[data-tab]').forEach(t=>t.classList.toggle('active',t===b));
  $('auth-title').textContent=signup?'새로운 대화를 시작해요.':'다시 만나 반가워요.';
  $('confirm-wrap').hidden=!signup;$('auth-confirm').required=signup;
  $('auth-password').autocomplete=signup?'new-password':'current-password';
  document.querySelector('.auth-submit').textContent=signup?'회원가입 화면 확인':'로그인 화면 확인';$('auth-status').textContent='';
}));
$('auth-form').addEventListener('submit',event=>{
  event.preventDefault();
  if(signup&&$('auth-password').value!==$('auth-confirm').value){$('auth-status').textContent='비밀번호가 서로 다릅니다.';return;}
  $('auth-status').textContent='입력 확인 완료! 실제 '+(signup?'회원가입':'로그인')+'은 백엔드 연결 후 사용할 수 있어요.';
  $('auth-password').value='';$('auth-confirm').value='';
});
renderHistory();renderChat();
