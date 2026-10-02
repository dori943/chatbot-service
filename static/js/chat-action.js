import { auth, syncAuthState, clearAuth, openLogin } from './auth-ui.js'
import { CHAT_PAGE_SIZE, request_chat, request_rooms, request_history, refresh_history, request_delete_room, chatError, uid, loadRooms, saveRooms } from './chat-service.js'
import { setDrawer, setBusy, setStatus, renderHistory, renderChat } from './chat-room.js'
import { toast } from './toast.js'

const $ = selector => document.querySelector(selector)

const MAX_QUESTION_LENGTH = 1000
const POLL_INTERVAL_MS    = 2000
const requests           = new Map()

let ownerId   = auth?.id ?? null
let draft     = null
let pollTimer = null
let paused    = false

export let chats    = loadRooms(ownerId)
export let activeId = new URLSearchParams(location.hash.slice(1)).get('room')
export let loading  = null

// 현재 방에 전송 중이거나 서버에서 처리 중인 질문이 있는지 확인한다.
export const isProcessing = () => requests.has(activeId)
    || chats.find(chat => chat.id === activeId)?.messages.some(message => message.status === 'processing')

// 현재 방 목록만 저장하고 저장 실패를 화면에 알린다.
const save = () => {
    if (saveRooms(ownerId, chats)) return true
    toast('방 목록을 저장하지 못했습니다. 대화 기록은 서버에서 다시 불러올 수 있습니다.')
    return false
}

// 이전 조회를 취소해 늦게 도착한 응답이 다른 화면을 덮지 않게 한다.
const cancelLoading = () => {
    clearTimeout(pollTimer)
    loading?.controller.abort()
    loading = null
}

// 처리 중인 질문이 있으면 잠시 후 상태를 다시 조회한다.
const schedulePoll = () => {
    clearTimeout(pollTimer)
    if (!paused && isProcessing() && !requests.has(activeId)) {
        pollTimer = setTimeout(() => loadChat(activeId, false, true), POLL_INTERVAL_MS)
    }
}

// 조회·삭제 오류를 표시하고 만료된 인증을 해제한다.
const showHistoryError = (error, token) => {
    if (error.name === 'AbortError') return
    if (error.status === 401) clearAuth(token)
    setStatus(error.message || '대화 기록을 불러오지 못했습니다.', 'error', { login: !auth })
}

// 방 목록과 선택한 방의 처리 상태를 조회하고 진행 중이면 다시 조회한다.
export const loadChat = async (id = activeId, refreshRooms = false, quiet = false) => {
    if (!auth || loading?.deleting) return
    const wasProcessing = id === activeId && isProcessing()
    cancelLoading()
    const request = { controller: new AbortController(), token: auth.token, userId: ownerId, refreshRooms }
    loading  = request
    activeId = id
    if (!quiet) {
        paused = false
        setStatus('대화 기록을 불러오는 중입니다…', 'loading')
        render()
    }

    try {
        if (refreshRooms) {
            const rooms = await request_rooms(request.token, request.controller.signal)
            if (loading !== request || ownerId !== request.userId) return
            const sending = chats.filter(chat => requests.has(chat.id) && !rooms.some(room => room.id === chat.id))
            chats = [...sending, ...rooms.map(room => {
                const previous = chats.find(chat => chat.id === room.id)
                return { ...room, messages: previous?.messages || [], beforeId: previous?.beforeId }
            })]
            if (!chats.some(chat => chat.id === id)) activeId = null
            save()
        }
        const current = chats.find(chat => chat.id === activeId)
        if (current) {
            const messages = quiet
                ? await refresh_history(current.id, current.messages, request.token, request.controller.signal)
                : await request_history(current.id, request.token, request.controller.signal)
            if (loading !== request || ownerId !== request.userId) return
            if (messages.length || !requests.has(current.id)) current.messages = messages
            if (!quiet || current.beforeId === undefined) {
                current.beforeId = messages.length >= CHAT_PAGE_SIZE * 2 ? messages[0].id : null
            }
            if (!messages.length && !requests.has(current.id)) {
                chats = chats.filter(chat => chat.id !== current.id)
                activeId = null
                save()
            }
            if (wasProcessing && messages.at(-1)?.status === 'success' && !isProcessing()) $('.question').value = ''
        }
        showChatStatus()
        return true
    } catch (error) {
        if (loading === request) showHistoryError(error, request.token)
    } finally {
        if (loading === request) {
            loading = null
            render(quiet)
            schedulePoll()
        }
    }
}

// 이전 대화 5건을 앞에 붙이고 읽던 위치를 유지한다.
export const loadEarlier = async () => {
    const current = chats.find(chat => chat.id === activeId)
    if (!auth || loading || !current?.beforeId) return
    clearTimeout(pollTimer)
    const request = { controller: new AbortController(), token: auth.token, userId: ownerId }
    loading = request
    setStatus('이전 대화를 불러오는 중입니다…', 'loading')
    setBusy(Boolean(isProcessing()), true, paused)

    try {
        const messages = await request_history(current.id, request.token, request.controller.signal, current.beforeId)
        if (loading !== request || ownerId !== request.userId) return
        current.messages.unshift(...messages)
        current.beforeId = messages.length === CHAT_PAGE_SIZE * 2 ? messages[0].id : null
        showChatStatus()
    } catch (error) {
        if (loading === request) showHistoryError(error, request.token)
    } finally {
        if (loading === request) {
            loading = null
            render(true, true)
            schedulePoll()
        }
    }
}

// 현재 방의 처리 상태와 마지막 실패를 표시한다.
const showChatStatus = () => {
    const messages = chats.find(chat => chat.id === activeId)?.messages || []
    const last = messages.at(-1)
    if (isProcessing()) return setStatus('답변을 생성하고 있습니다…', 'loading')
    if (last?.status === 'error' || last?.status === 'timeout') return setStatus(last.text, 'error', { retry: true })
    setStatus()
}

// 입력 글자 수와 입력창 높이를 갱신한다.
export const updateInput = () => {
    const input = $('.question')
    if (!ownerId && draft) draft.question = input.value

    $('.char-count').textContent = `${input.value.length.toLocaleString()} / ${MAX_QUESTION_LENGTH.toLocaleString()}`
    input.style.height = 'auto'
    input.style.height = Math.min(input.scrollHeight, 150) + 'px'
}

// 대화 목록·메시지·입력 상태를 함께 갱신한다.
export const render = (quiet = false, prepend = false) => {
    history.replaceState(null, '', location.pathname + location.search + (activeId ? '#room=' + encodeURIComponent(activeId) : ''))
    renderHistory(chats, activeId, Boolean(loading?.deleting || loading?.refreshRooms))
    renderChat(chats.find(chat => chat.id === activeId), quiet, prepend)
    setBusy(Boolean(isProcessing()), Boolean(loading), paused)
    updateInput()
}

// 입력과 선택 상태를 비우고 새 대화를 시작한다.
export const newChat = () => {
    if (loading?.deleting) return
    cancelLoading()

    if (!ownerId) draft = null
    activeId  = null
    paused    = false
    $('.question').value = ''

    setStatus()
    render()
    setDrawer(false)
    $('.question').focus()
}

// 서버에서 방 기록을 삭제한 뒤 화면과 방 목록을 갱신한다.
export const deleteChat = async () => {
    if (!auth || isProcessing() || loading || !activeId) return
    clearTimeout(pollTimer)
    const request = { controller: new AbortController(), token: auth.token, deleting: true }
    loading = request
    setStatus('대화방을 삭제하는 중입니다…', 'loading')
    render()

    try {
        await request_delete_room(activeId, request.token, request.controller.signal)
        if (loading !== request) return
        chats     = chats.filter(chat => chat.id !== activeId)
        activeId  = null
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
    if (loading?.deleting) return

    $('.question').value = ''
    setDrawer(false)
    loadChat(id)
}

// 계정에 맞는 대화를 불러오고 같은 계정으로 재로그인하면 작성 중인 질문을 복원한다.
export const switchChatOwner = (id, reason) => {
    if (id === ownerId) return

    const preserveDraft = ownerId && !id && ['expired', 'unauthorized'].includes(reason)
    if (preserveDraft) draft = { id: ownerId, question: $('.question').value, activeId }
    else if (id !== draft?.id) draft = null

    requests.forEach(request => request.controller.abort())
    requests.clear()
    cancelLoading()
    paused    = false
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

// 응답 대기와 상태 조회를 멈추며 서버에 접수된 작업은 유지한다.
export const stopWaiting = () => {
    paused = true
    cancelLoading()
    requests.get(activeId)?.controller.abort()
    setStatus('응답 대기를 중지했습니다. 서버에서는 계속 처리됩니다. 방을 다시 선택하면 상태를 확인할 수 있습니다.')
    render()
}

// 마지막으로 실패한 질문을 새 요청으로 다시 전송한다.
export const retryChat = () => {
    if (isProcessing() || loading) return
    const messages = chats.find(chat => chat.id === activeId)?.messages || []
    const last = messages.at(-1)
    if (!['error', 'timeout'].includes(last?.status)) return
    $('.question').value = messages.at(-2).text
    $('.chat-form').requestSubmit()
}

// 질문을 전송하고 원래 방에 결과를 반영하며 실패한 질문도 남긴다.
export const handleSubmit = async event => {
    event.preventDefault()
    if (isProcessing() || loading) return

    syncAuthState()
    if (!auth) return setStatus('로그인 후 질문을 보내 주세요.', 'error', { login: true })
    if (loading) return

    const question = $('.question').value.trim()
    if (!question) return setStatus('메시지를 입력해 주세요.', 'error')
    if (Array.from(question).length > MAX_QUESTION_LENGTH) return setStatus('메시지는 1,000자 이내로 입력해 주세요.', 'error')

    let current = chats.find(chat => chat.id === activeId)
    if (!current) {
        current = {
            id       : uid(),
            title    : Array.from(question).slice(0, 30).join(''),
            messages : []
        }
        chats    = [current, ...chats]
        activeId = current.id
    }

    const request = { controller: new AbortController(), token: auth.token, userId: ownerId, lastId: current.messages.at(-1)?.id || 0 }
    const response = { role: 'assistant', status: 'processing', text: '답변을 생성하고 있습니다…' }
    requests.set(current.id, request)
    paused = false
    clearTimeout(pollTimer)
    current.messages.push({ role: 'user', text: question }, response)
    save()
    showChatStatus()
    render()

    try {
        const { data } = await request_chat(question, current.id, current.title, request.token, request.controller.signal)
        if (requests.get(current.id) !== request) return

        Object.assign(response, { id: data.id, status: 'success', text: data.answer })
        const messages = chats.find(chat => chat.id === current.id)?.messages
        const saved = messages?.find(message => message.role === 'assistant' && message.id === data.id)
        if (saved) Object.assign(saved, response)
        else if (messages && !messages.includes(response)) messages.push({ role: 'user', text: question }, response)
        if (activeId === current.id) $('.question').value = ''
    } catch (error) {
        if (requests.get(current.id) !== request) return

        const cancelled    = error.name === 'AbortError'
        const code         = error.errorCode
        const unauthorized = code === 'UNAUTHORIZED' || error.status === 401
        if (unauthorized) clearAuth(request.token)
        if (unauthorized && !auth) openLogin()

        if (!cancelled && code !== 'CLIENT_TIMEOUT' && error.status) {
            Object.assign(response, { status: 'error', text: chatError(code) })
        }
        request.error = error
    } finally {
        if (requests.get(current.id) === request) {
            requests.delete(current.id)
            if (activeId === current.id && !paused) {
                const loaded = await loadChat(current.id, true, true)
                if (!loaded || ownerId !== request.userId || activeId && activeId !== current.id) return
                const last = chats.find(chat => chat.id === activeId)?.messages.at(-1)
                const completed = last?.status === 'success' && last.id > request.lastId
                if (request.error && !isProcessing() && !completed) {
                    const message = request.error.errorCode?.startsWith('AI_') ? chatError(request.error.errorCode) : request.error.message
                    setStatus(message, 'error', { retry: ['error', 'timeout'].includes(last?.status) })
                }
                if (!$('.auth-dialog').open) $('.question').focus()
            }
            if (activeId === current.id) render(true)
        }
    }
}

