import { toast } from './toast.js'

const $  = selector => document.querySelector(selector)
const $$ = selector => document.querySelectorAll(selector)

// 모바일 대화 목록을 열거나 닫는다.
export const setDrawer = open => {
    $('.sidebar')    .classList.toggle('is-open', open)
    $('.scrim')      .hidden = !open
    $('.menu-button').setAttribute('aria-expanded', String(open))
    if (open) $('.history-search').focus()
}

// 요청 중 입력과 대화 변경을 잠그고 중지 버튼을 표시한다.
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
export const setStatus = (message = '', type = 'info', { requestId = null, retry = false, login = false } = {}) => {
    $('.status')    .dataset.state = type
    $('.status')    .textContent   = message
    $('.status')    .setAttribute('role', type === 'error' ? 'alert' : 'status')
    $('.question')  .removeAttribute('aria-invalid')

    $('.request-id').textContent = requestId ? `요청 ID: ${requestId}` : ''
    $('.request-id').hidden      = !requestId
    $('.retry')     .hidden      = !retry
    $('.reauth')    .hidden      = !login
}

// 검색어에 맞는 대화 목록과 선택 상태를 표시한다.
export const renderHistory = (chats, activeId, busy) => {
    const query = $('.history-search').value.trim().toLowerCase()
    const buttons = chats.filter(chat => chat.title.toLowerCase().includes(query)).map(chat => {
        const button = document.createElement('button')
        button.type         = 'button'
        button.className    = 'history-item' + (chat.id === activeId ? ' active' : '')
        button.textContent  = chat.title
        button.title        = chat.title
        button.dataset.room = chat.id
        button.disabled     = busy
        return button
    })

    $('.history-list').replaceChildren(...buttons)
    $('.history-count').textContent = chats.length
    $('.history-empty').hidden      = buttons.length > 0
    $('.history-empty').textContent = query ? '검색 결과가 없습니다.' : '아직 대화가 없습니다. 첫 질문을 남겨보세요.'
}

// 답변을 복사하고 자동 복사가 안 되면 직접 복사할 텍스트를 선택한다.
export const copyText = async article => {
    const text = article.querySelector('.message-text').textContent

    try {
        await navigator.clipboard.writeText(text)
        toast('답변을 복사했습니다.')
    } catch {
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
export const renderChat = current => {
    const messages   = current?.messages || []
    const transcript = $('.transcript')

    $('.welcome')           .hidden      = messages.length > 0
    transcript              .hidden      = !messages.length
    $('.conversation-title').textContent = current?.title || '새로운 대화'

    transcript.replaceChildren()
    if (messages.length) transcript.append($('.chat-tools-template').content.cloneNode(true))
    messages.forEach(message => {
        const article = $('.message-template').content.firstElementChild.cloneNode(true)
        article.classList.add(message.role)
        article.querySelector('b')            .textContent = message.role === 'user' ? '나' : '담다'
        article.querySelector('.message-text').textContent = message.text
        article.querySelector('.copy-button') .hidden      = message.role !== 'assistant'
        transcript.append(article)
    })

    const pane = $('.chat-body')
    requestAnimationFrame(() => pane.scrollTop = pane.scrollHeight)
}
