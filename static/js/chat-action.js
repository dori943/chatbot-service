import { auth, syncAuthState, clearAuth, openLogin } from './auth-ui.js'
import { request_chat, request_rooms, request_history, request_delete_room, uid, loadRooms, saveRooms } from './chat-service.js'
import { setDrawer, setBusy, setStatus, renderHistory, renderChat } from './chat-room.js'
import { toast } from './toast.js'

const $ = selector => document.querySelector(selector)

const MAX_QUESTION_LENGTH = 5000

let ownerId   = auth?.id ?? null
let retryRoom = null
let draft     = null

export let chats    = loadRooms(ownerId)
export let activeId = null
export let pending  = null
export let loading  = null

// 현재 방 목록만 저장하고 저장 실패를 화면에 알린다.
const save = () => {
    if (saveRooms(ownerId, chats)) return true
    toast('방 목록을 저장하지 못했습니다. 대화 기록은 서버에서 다시 불러올 수 있습니다.')
    return false
}

// 이전 조회를 취소해 늦게 도착한 응답이 다른 화면을 덮지 않게 한다.
const cancelLoading = () => {
    loading?.controller.abort()
    loading = null
}

// 조회·삭제 오류를 표시하고 만료된 인증을 해제한다.
const showHistoryError = (error, token) => {
    if (error.name === 'AbortError') return
    if (error.status === 401) clearAuth(token)
    setStatus(error.message || '대화 기록을 불러오지 못했습니다.', 'error', { login: !auth })
}

// 방 목록과 선택한 방의 완료된 대화를 서버에서 갱신한다.
export const loadChat = async (id = activeId, refreshRooms = false) => {
    if (!auth || pending || loading?.deleting) return
    cancelLoading()
    const request = { controller: new AbortController(), token: auth.token, userId: ownerId, refreshRooms }
    loading  = request
    activeId = id
    chats.forEach(chat => { if (chat.id !== id) chat.messages = [] })
    setStatus('대화 기록을 불러오는 중입니다…', 'loading')
    render()

    try {
        if (refreshRooms) {
            const rooms = await request_rooms(request.token, request.controller.signal)
            if (loading !== request || ownerId !== request.userId) return
            const current = chats.find(chat => chat.id === id)
            chats = rooms.map(room => room.id === id && current ? { ...room, messages: current.messages } : room)
            if (!chats.some(chat => chat.id === id)) activeId = null
            save()
        }
        const current = chats.find(chat => chat.id === activeId)
        if (current) {
            const messages = await request_history(current.id, request.token, request.controller.signal)
            if (loading !== request || ownerId !== request.userId) return
            current.messages = messages
            if (!messages.length) {
                chats = chats.filter(chat => chat.id !== current.id)
                activeId = null
                save()
            }
        }
        setStatus()
    } catch (error) {
        if (loading === request) showHistoryError(error, request.token)
    } finally {
        if (loading === request) {
            loading = null
            render()
        }
    }
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
    renderHistory(chats, activeId, Boolean(pending || loading?.deleting || loading?.refreshRooms))
    renderChat(chats.find(chat => chat.id === activeId))
    setBusy(Boolean(pending), Boolean(loading))
    updateInput()
}

// 입력과 선택 상태를 비우고 새 대화를 시작한다.
export const newChat = () => {
    if (pending || loading?.deleting) return
    cancelLoading()
    chats.forEach(chat => chat.messages = [])

    if (!ownerId) draft = null
    activeId  = null
    retryRoom = null
    $('.question').value = ''

    setStatus()
    render()
    setDrawer(false)
    $('.question').focus()
}

// 서버에서 방 기록을 삭제한 뒤 화면과 방 목록을 갱신한다.
export const deleteChat = async () => {
    if (!auth || pending || loading || !activeId) return
    const request = { controller: new AbortController(), token: auth.token, deleting: true }
    loading = request
    setStatus('대화방을 삭제하는 중입니다…', 'loading')
    render()

    try {
        await request_delete_room(activeId, request.token, request.controller.signal)
        if (loading !== request) return
        chats     = chats.filter(chat => chat.id !== activeId)
        activeId  = null
        retryRoom = null
        save()
        setStatus()
        toast('대화방을 삭제했습니다.')
    } catch (error) {
        if (loading === request) showHistoryError(error, request.token)
    } finally {
        if (loading === request) {
            loading = null
            render()
        }
    }
}

// 선택한 대화로 전환하고 목록을 닫는다.
export const selectChat = id => {
    if (pending || loading?.deleting) return

    retryRoom = null
    setDrawer(false)
    loadChat(id)
}

// 계정에 맞는 대화를 불러오고 같은 계정으로 재로그인하면 작성 중인 질문을 복원한다.
export const switchChatOwner = (id, reason) => {
    if (id === ownerId) return

    const preserveDraft = ownerId && !id && ['expired', 'unauthorized'].includes(reason)
    if (preserveDraft) draft = { id: ownerId, question: $('.question').value, activeId }
    else if (id !== draft?.id) draft = null

    pending?.controller.abort()
    cancelLoading()
    pending   = null
    retryRoom = null
    ownerId   = id
    chats     = loadRooms(id)

    const restoreDraft = id && draft?.id === id
    activeId = restoreDraft ? draft.activeId : null
    $('.question')      .value = preserveDraft || restoreDraft ? draft.question : ''
    $('.history-search').value = ''
    if (restoreDraft) draft = null

    if (preserveDraft) setStatus('로그인이 만료됐습니다. 같은 계정으로 다시 로그인하면 질문을 이어서 보낼 수 있습니다.', 'error')
    else setStatus()
    render()
    if (id) loadChat(activeId, true)
}

// 질문을 전송하고 응답·취소·실패에 따라 대화를 갱신한다.
export const handleSubmit = async event => {
    event.preventDefault()
    if (pending || loading) return

    syncAuthState()
    if (!auth) return setStatus('로그인 후 질문을 보내 주세요.', 'error', { login: true })
    if (loading) return

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
        chats    = [current, ...chats]
        activeId = current.id
    }

    const request = { controller: new AbortController(), token: auth.token }
    let completed = false
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
        completed = true
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
            if (completed) await loadChat(current.id, true)
            else render()
            if (!$('.auth-dialog').open) $('.question').focus()
        }
    }
}

