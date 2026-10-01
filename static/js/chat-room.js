// ==============================================================================
// [채팅 화면을 그리는 담당: chat-room.js]
// 이전 chat.js에서 DOM 렌더링을 분리했다. 이름의 room은 DB 방 테이블을 관리한다는 뜻이 아니다.
// chat-action이 상태(chats·activeId·pending)를 결정하고, 이 파일은 받은 값으로 화면을 표현한다.
// renderHistory = 목록 / renderChat = 메시지 / setBusy = 입력 잠금 / setStatus = 상태·오류 안내.
// 서버 호출·JWT 처리·대화 저장은 하지 않는다. 화면 클릭을 실제 행동에 연결하는 곳은 chat-ui.js다.
// ==============================================================================
import { toast } from './toast.js'

const $  = selector => document.querySelector(selector)
const $$ = selector => document.querySelectorAll(selector)

// 모바일 대화 목록을 열거나 닫는다.
// CSS 클래스, 배경 가림막, aria-expanded를 함께 바꿔 보이는 상태와 접근성 상태를 맞춘다.
export const setDrawer = open => {
    $('.sidebar')    .classList.toggle('is-open', open)
    $('.scrim')      .hidden = !open
    $('.menu-button').setAttribute('aria-expanded', String(open))
    if (open) $('.history-search').focus()
}

// 요청 중 입력과 대화 변경을 잠그고 중지 버튼을 표시한다.
// UI 잠금은 중복 조작을 줄이기 위한 것. 액션 함수의 if (pending)도 따로 두어 상태 변경을 방어한다.
// 대화 목록 버튼의 disabled는 renderHistory가 busy 인자를 받아 생성할 때 지정한다.
export const setBusy = busy => {
    $('.send-button').hidden   = busy
    $('.stop-button').hidden   = !busy
    $('.question')   .disabled = busy
    $('.retry')      .disabled = busy

    $('.chat-form')  .setAttribute('aria-busy', String(busy))
    $('.transcript') .setAttribute('aria-busy', String(busy))
    $$('[data-new], [data-prompt], .delete-chat').forEach(button => button.disabled = busy)
}

// 처리 상태와 재시도·로그인 안내를 표시한다.
// 세 번째 인자는 선택 옵션 객체다. 실제로 재시도/재로그인할지는 액션이 결정하고 여기서는 표시만 한다.
// 오류 코드를 해석한 결과와 requestId를 분리해 받으므로 화면 함수가 HTTP 정책을 다시 판단하지 않는다.
export const setStatus = (message = '', type = 'info', { requestId = null, retry = false, login = false } = {}) => {
    $('.status')    .dataset.state = type
    $('.status')    .textContent   = message
    $('.status')    .setAttribute('role', type === 'error' ? 'alert' : 'status')
    // 이전 입력 오류 표시를 초기화한다. 이번 오류가 INVALID_INPUT이면 액션에서 다시 true로 지정한다.
    $('.question')  .removeAttribute('aria-invalid')

    $('.request-id').textContent = requestId ? `요청 ID: ${requestId}` : ''
    $('.request-id').hidden      = !requestId
    $('.retry')     .hidden      = !retry
    $('.reauth')    .hidden      = !login
}

// 검색어에 맞는 대화 목록과 선택 상태를 표시한다.
// [데이터 → DOM] filter로 검색 → map으로 버튼 생성 → replaceChildren으로 기존 목록 교체.
// 각 버튼의 data-room은 chat-ui의 이벤트 위임에서 선택할 방 ID를 찾는 연결 고리다.
export const renderHistory = (chats, activeId, busy) => {
    const query = $('.history-search').value.trim().toLowerCase()
    const buttons = chats.filter(chat => chat.title.toLowerCase().includes(query)).map(chat => {
        const button = document.createElement('button')
        button.type         = 'button'
        button.className    = 'history-item' + (chat.id === activeId ? ' active' : '')
        // 사용자 제목을 HTML 문자열로 삽입하지 않는다. title 속성은 전체 제목을 툴팁으로 보여준다.
        button.textContent  = chat.title
        button.title        = chat.title
        button.dataset.room = chat.id
        button.disabled     = busy
        return button
    })

    // ...buttons는 배열을 개별 DOM 인자로 펼친다. 숫자는 검색 결과 수가 아니라 전체 로컬 방 수다.
    $('.history-list').replaceChildren(...buttons)
    $('.history-count').textContent = chats.length
    $('.history-empty').hidden      = buttons.length > 0
    $('.history-empty').textContent = query ? '검색 결과가 없습니다.' : '아직 대화가 없습니다. 첫 질문을 남겨보세요.'
}

// 답변을 복사하고 자동 복사가 안 되면 직접 복사할 텍스트를 선택한다.
// 클립보드 권한/환경 차이로 실패해도 답변 자체를 잃지 않도록 수동 복사 경로를 제공한다.
export const copyText = async article => {
    const text = article.querySelector('.message-text').textContent

    try {
        await navigator.clipboard.writeText(text)
        toast('답변을 복사했습니다.')
    } catch {
        // textarea를 재사용하고 select()만 수행한다. 이 경로는 사용자가 Ctrl+C/⌘C를 눌러야 복사된다.
        let area = article.querySelector('.fallback-copy')
        if (!area) {
            area = document.createElement('textarea')
            area.readOnly  = true
            area.className = 'fallback-copy'
            area.setAttribute('aria-label', '복사할 답변')
            article.append(area)
        }

        area.value = text
        area.focus()
        area.select()
        toast('텍스트를 선택했습니다. ⌘C 또는 Ctrl+C로 복사하세요.')
    }
}

// 선택한 대화의 메시지와 삭제·복사 버튼을 표시한다.
// index.html의 <template>은 화면에 즉시 보이지 않는 원본이다. cloneNode(true)로 자식까지 복제한다.
// 이벤트를 복제된 버튼마다 붙이지 않고 chat-ui가 상위 .transcript에서 한 번 받아 처리한다.
export const renderChat = current => {
    const messages   = current?.messages || []
    const transcript = $('.transcript')

    $('.welcome')           .hidden      = messages.length > 0
    transcript              .hidden      = !messages.length
    $('.conversation-title').textContent = current?.title || '새로운 대화'

    // 이전 DOM을 비우고 현재 상태로 다시 그린다. 실제 메시지 데이터의 변경은 액션이 수행한다.
    transcript.replaceChildren()
    if (messages.length) transcript.append($('.chat-tools-template').content.cloneNode(true))
    messages.forEach(message => {
        const article = $('.message-template').content.firstElementChild.cloneNode(true)
        article.classList.add(message.role)
        article.querySelector('b')            .textContent = message.role === 'user' ? '나' : '담다'
        // 답변이 <script>나 Markdown처럼 보여도 textContent로 표시하므로 이 경로에서는 HTML로 실행하지 않는다.
        article.querySelector('.message-text').textContent = message.text
        article.querySelector('.copy-button') .hidden      = message.role !== 'assistant'
        transcript.append(article)
    })

    const pane = $('.chat-body')
    // DOM을 바꾼 뒤 다음 화면 갱신 시점에 새 콘텐츠 높이를 기준으로 맨 아래까지 이동한다.
    requestAnimationFrame(() => pane.scrollTop = pane.scrollHeight)
}
