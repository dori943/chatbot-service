import { auth, syncAuthState, clearAuth, openLogin } from './auth-ui.js'
import { MAX_CHATS, request_chat, uid, loadChats, saveChats } from './chat-service.js'
import { toast, setDrawer, setBusy, setStatus, renderHistory, renderChat } from './chat-room.js'

const $ = selector => document.querySelector(selector)

const MAX_QUESTION_LENGTH = 5000

let ownerId   = auth?.id ?? null
let retryRoom = null
let draft     = null

export let chats    = loadChats(ownerId)
export let activeId = null
export let pending  = null

// 현재 대화를 저장하고 저장 실패를 화면에 알린다.
const save = () => {
    if (saveChats(ownerId, chats)) return true
    toast('저장하지 못했습니다. 새로고침하면 이전 기록이 다시 나타나거나 이번 변경이 사라질 수 있습니다.')
    return false
}

// 입력 글자 수·입력창 높이·재시도 버튼을 갱신한다.
export const updateInput = () => {
    const input = $('.question')
    if (!ownerId && draft) draft.question = input.value
    if (retryRoom && input.value.trim() !== retryRoom.question) $('.retry').hidden = true

    $('.char-count').textContent = `${Array.from(input.value).length.toLocaleString()} / ${MAX_QUESTION_LENGTH.toLocaleString()}`
    input.style.height = 'auto'
    input.style.height = Math.min(input.scrollHeight, 150) + 'px'
}

// 대화 목록·메시지·입력 상태를 함께 갱신한다.
export const render = () => {
    renderHistory(chats, activeId, Boolean(pending))
    renderChat(chats.find(chat => chat.id === activeId))
    setBusy(Boolean(pending))
    updateInput()
}

// 입력과 선택 상태를 비우고 새 대화를 시작한다.
export const newChat = () => {
    if (pending) return

    if (!ownerId) draft = null
    activeId  = null
    retryRoom = null
    $('.question').value = ''

    setStatus()
    render()
    setDrawer(false)
    $('.question').focus()
}

// 선택한 대화를 현재 브라우저의 기록에서 삭제한다.
export const deleteChat = () => {
    if (pending) return

    chats     = chats.filter(chat => chat.id !== activeId)
    activeId  = null
    retryRoom = null

    setStatus()
    if (save()) toast('이 브라우저에서 대화를 삭제했습니다.')
    render()
}

// 선택한 대화로 전환하고 목록을 닫는다.
export const selectChat = id => {
    if (pending) return

    activeId  = id
    retryRoom = null

    setStatus()
    render()
    setDrawer(false)
}

// 계정에 맞는 대화를 불러오고 같은 계정으로 재로그인하면 작성 중인 질문을 복원한다.
export const switchChatOwner = (id, reason) => {
    if (id === ownerId) return

    const preserveDraft = ownerId && !id && ['expired', 'unauthorized'].includes(reason)
    if (preserveDraft) draft = { id: ownerId, question: $('.question').value, activeId }
    else if (id !== draft?.id) draft = null

    pending?.controller.abort()
    pending   = null
    retryRoom = null
    ownerId   = id
    chats     = loadChats(id)

    const restoreDraft = id && draft?.id === id
    activeId = restoreDraft && chats.some(chat => chat.id === draft.activeId) ? draft.activeId : null
    $('.question')      .value = preserveDraft || restoreDraft ? draft.question : ''
    $('.history-search').value = ''
    if (restoreDraft) draft = null

    if (preserveDraft) setStatus('로그인이 만료됐습니다. 같은 계정으로 다시 로그인하면 질문을 이어서 보낼 수 있습니다.', 'error')
    else setStatus()
    render()
}

// 질문을 전송하고 응답·취소·실패에 따라 대화를 갱신한다.
export const handleSubmit = async event => {
    event.preventDefault()
    if (pending) return

    syncAuthState()
    if (!auth) return setStatus('로그인 후 질문을 보내 주세요.', 'error', { login: true })

    const question = $('.question').value.trim()
    if (!question) return setStatus('메시지를 입력해 주세요.', 'error')
    if (Array.from(question).length > MAX_QUESTION_LENGTH) return setStatus('메시지는 5,000자 이내로 입력해 주세요.', 'error')

    let current = chats.find(chat => chat.id === activeId)
    const previousChats = chats
    const isNewChat     = !current
    if (isNewChat) {
        current = {
            id       : retryRoom?.id || uid(),
            title    : retryRoom?.title || Array.from(question).slice(0, 30).join(''),
            messages : []
        }
        chats    = [current, ...chats].slice(0, MAX_CHATS)
        activeId = current.id
    }

    const request = { controller: new AbortController(), token: auth.token }
    pending = request
    current.messages.push({ role: 'user', text: question })
    setStatus('답변을 기다리고 있어요…', 'loading')
    render()

    try {
        const { data } = await request_chat(question, current.id, current.title, request.token, request.controller.signal)
        if (pending !== request) return

        current.messages.push({ role: 'assistant', text: data.answer })
        $('.question').value = ''
        retryRoom = null
        setStatus()
        save()
    } catch (error) {
        if (pending !== request) return

        current.messages.pop()
        if (isNewChat) {
            chats    = previousChats
            activeId = null
        }

        const cancelled    = error.name === 'AbortError'
        const code         = error.errorCode || { 422: 'INVALID_INPUT', 504: 'AI_TIMEOUT' }[error.status]
        const unauthorized = code === 'UNAUTHORIZED' || error.status === 401
        if (unauthorized) clearAuth(request.token)
        else retryRoom = { id: current.id, title: current.title, question }

        setStatus(
            cancelled ? '응답 대기를 중지했어요. 입력한 질문은 남겨두었습니다.' : error.message || '응답을 받지 못했어요. 다시 시도해 주세요.',
            cancelled ? 'info' : 'error',
            {
                requestId : error.requestId,
                retry     : !unauthorized && ['AI_TIMEOUT', 'CLIENT_TIMEOUT'].includes(code),
                login     : unauthorized && !auth
            }
        )
        if (unauthorized && !auth) openLogin()
        if (code === 'INVALID_INPUT') $('.question').setAttribute('aria-invalid', 'true')
    } finally {
        if (pending === request) {
            pending = null
            render()
            if (!$('.auth-dialog').open) $('.question').focus()
        }
    }
}

