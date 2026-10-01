// ==============================================================================
// [채팅 상태와 처리 순서를 조정하는 담당: chat-action.js]
// 이전 chat.js에서 "무엇을 어떤 순서로 변경할지"를 모은 부분이다.
// chat-ui는 이벤트 연결, chat-room은 DOM 표현, chat-service는 API 계약·로컬 저장을 맡는다.
// 이 파일은 그 사이에서 요청 중복 방지, 임시 메시지, 실패 복구, 계정 전환을 연결한다.
// 읽는 순서: 상태 변수 → render → handleSubmit → switchChatOwner → 새 방/삭제/선택.
// 서버의 chat_main.chat이 인증 이후 AI·저장 흐름을 조정하듯, 여기서는 브라우저의 작업 흐름을 조정한다.
// ==============================================================================
import { auth, syncAuthState, clearAuth, openLogin } from './auth-ui.js'
import { MAX_CHATS, request_chat, uid, loadChats, saveChats } from './chat-service.js'
import { setDrawer, setBusy, setStatus, renderHistory, renderChat } from './chat-room.js'
import { toast } from './toast.js'

const $ = selector => document.querySelector(selector)

const MAX_QUESTION_LENGTH = 5000

// ownerId: 지금 화면 대화의 주인. auth는 인증 모듈의 live binding이므로 서로 같은 시점인지 확인해야 한다.
// retryRoom: 실패 후 다시 보낼 방 ID·제목·질문. 재전송 때 새 방이 계속 만들어지지 않도록 보존한다.
// draft: 만료/401로 잠시 로그아웃했을 때 같은 계정에만 돌려줄 미전송 질문. 서버 기록이 아니다.
let ownerId   = auth?.id ?? null
let retryRoom = null
let draft     = null

// export let 상태는 chat-ui가 읽는다. pending은 단순 true/false가 아니라 { controller, token } 요청 객체다.
// 요청마다 다른 객체를 만들어 "아직 이 요청의 화면인가?"를 ===로 판정한다.
export let chats    = loadChats(ownerId)
export let activeId = null
export let pending  = null

// 현재 대화를 저장하고 저장 실패를 화면에 알린다.
// 여기의 저장은 localStorage다. 서버 응답에 성공한 뒤 이 저장만 실패해도 메모리의 답변은 화면에 남긴다.
const save = () => {
    if (saveChats(ownerId, chats)) return true
    toast('저장하지 못했습니다. 새로고침하면 이전 기록이 다시 나타나거나 이번 변경이 사라질 수 있습니다.')
    return false
}

// 입력 글자 수·입력창 높이·재시도 버튼을 갱신한다.
export const updateInput = () => {
    const input = $('.question')
    if (!ownerId && draft) draft.question = input.value
    // 실패했던 질문을 수정하면 기존 질문용 재시도 버튼을 숨긴다. 버튼 표시는 자동 요청과 별개다.
    if (retryRoom && input.value.trim() !== retryRoom.question) $('.retry').hidden = true

    // .length만 사용하면 일부 이모지가 UTF-16 두 단위로 계산되므로 코드 포인트 배열로 길이를 센다.
    $('.char-count').textContent = `${Array.from(input.value).length.toLocaleString()} / ${MAX_QUESTION_LENGTH.toLocaleString()}`
    input.style.height = 'auto'
    input.style.height = Math.min(input.scrollHeight, 150) + 'px'
}

// 대화 목록·메시지·입력 상태를 함께 갱신한다.
// 여러 액션이 같은 렌더 순서를 재사용한다. Boolean(pending)은 요청 객체를 화면 잠금용 true/false로 변환한다.
export const render = () => {
    renderHistory(chats, activeId, Boolean(pending))
    renderChat(chats.find(chat => chat.id === activeId))
    setBusy(Boolean(pending))
    updateInput()
}

// 입력과 선택 상태를 비우고 새 대화를 시작한다.
// 여기서는 빈 방을 서버에 생성하지 않는다. 실제 방 ID와 첫 메시지는 첫 질문을 보낼 때 만든다.
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
// DELETE API는 호출하지 않는다. filter로 새 배열을 만들고 로컬 저장·화면만 갱신한다.
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
// 방 전환 시 다음 질문용 재시도 정보를 정리한다. 서버 문맥은 실제 전송한 room_id로 구분된다.
export const selectChat = id => {
    if (pending) return

    activeId  = id
    retryRoom = null

    setStatus()
    render()
    setDrawer(false)
}

// 계정에 맞는 대화를 불러오고 같은 계정으로 재로그인하면 작성 중인 질문을 복원한다.
// [초안의 소유권]
// 만료/401로 A → 비로그인: A의 질문·선택 방을 임시 보관.
// 비로그인 → A: A의 초안만 복원. 비로그인 → B 또는 명시적 로그아웃: 이전 초안 정리.
// 동일 계정의 토큰 갱신처럼 id가 같으면 방 목록 자체를 전환할 필요가 없어 바로 반환한다.
export const switchChatOwner = (id, reason) => {
    if (id === ownerId) return

    const preserveDraft = ownerId && !id && ['expired', 'unauthorized'].includes(reason)
    if (preserveDraft) draft = { id: ownerId, question: $('.question').value, activeId }
    else if (id !== draft?.id) draft = null

    // 실제 fetch 중지를 요청하고 pending도 비운다. 늦게 돌아온 응답은 handleSubmit의 동일성 검사에서 무시한다.
    pending?.controller.abort()
    pending   = null
    retryRoom = null
    ownerId   = id
    chats     = loadChats(id)

    const restoreDraft = id && draft?.id === id
    // 예전에 선택한 방이 로컬 목록에 아직 있을 때만 방 선택도 복원한다.
    activeId = restoreDraft && chats.some(chat => chat.id === draft.activeId) ? draft.activeId : null
    $('.question')      .value = preserveDraft || restoreDraft ? draft.question : ''
    $('.history-search').value = ''
    if (restoreDraft) draft = null

    if (preserveDraft) setStatus('로그인이 만료됐습니다. 같은 계정으로 다시 로그인하면 질문을 이어서 보낼 수 있습니다.', 'error')
    else setStatus()
    render()
}

// 질문을 전송하고 응답·취소·실패에 따라 대화를 갱신한다.
// ==============================================================================
// [전송 파이프라인: handleSubmit]
// 인증/입력 재확인 → 방 선택/생성 → 내 질문을 임시 표시 → HTTP 대기 → 성공 저장 또는 화면 복구.
// await 전후에는 계정/현재 요청이 달라질 수 있다. catch와 finally에서도 같은 요청인지 확인한다.
// ==============================================================================
export const handleSubmit = async event => {
    event.preventDefault()
    if (pending) return

    // 오래된 화면의 로그인 표시만 믿지 않고 토큰 만료·저장소 변경을 전송 직전에 다시 반영한다.
    syncAuthState()
    if (!auth) return setStatus('로그인 후 질문을 보내 주세요.', 'error', { login: true })

    const question = $('.question').value.trim()
    if (!question) return setStatus('메시지를 입력해 주세요.', 'error')
    if (Array.from(question).length > MAX_QUESTION_LENGTH) return setStatus('메시지는 5,000자 이내로 입력해 주세요.', 'error')

    let current = chats.find(chat => chat.id === activeId)
    // 새 방 생성에서는 원본 배열을 수정하지 않고 새 배열을 만들어 previousChats로 되돌릴 수 있다.
    // 기존 방의 메시지는 같은 객체를 쓰므로 실패 시 아래 pop()으로 임시 질문을 제거한다.
    const previousChats = chats
    const isNewChat     = !current
    if (isNewChat) {
        current = {
            // 실패한 첫 질문의 재시도라면 이전 ID·제목을 사용한다. 요청 중복을 서버에서 제거하는 기능은 아니다.
            id       : retryRoom?.id || uid(),
            title    : retryRoom?.title || Array.from(question).slice(0, 30).join(''),
            messages : []
        }
        chats    = [current, ...chats].slice(0, MAX_CHATS)
        activeId = current.id
    }

    // 요청 당시 토큰을 고정해 보낸다. 나중에 401이 와도 clearAuth가 이 토큰만 삭제 대상으로 삼는다.
    const request = { controller: new AbortController(), token: auth.token }
    pending = request
    current.messages.push({ role: 'user', text: question })
    // [낙관적 표시] 서버 성공 전에 내 말풍선을 먼저 보여주지만, localStorage 저장은 성공 뒤에 한다.
    setStatus('답변을 기다리고 있어요…', 'loading')
    render()

    try {
        const { data } = await request_chat(question, current.id, current.title, request.token, request.controller.signal)
        // 계정 전환 등으로 이 요청이 폐기됐으면 다른 계정 화면에 답변을 붙이지 않는다.
        if (pending !== request) return

        // 현재 서비스 계약은 { data, requestId }. 이 경로는 data.answer를 받아 추가하며 별도 문자열 검사는 없다.
        current.messages.push({ role: 'assistant', text: data.answer })
        $('.question').value = ''
        retryRoom = null
        setStatus()
        save()
    } catch (error) {
        if (pending !== request) return

        // [화면 복구] 실패한 전송의 임시 질문 제거. 첫 질문이었다면 임시 방도 생성 전 목록으로 되돌린다.
        // 서버에서 이미 저장한 실패 행을 지우는 DB rollback과는 다르다.
        current.messages.pop()
        if (isNewChat) {
            chats    = previousChats
            activeId = null
        }

        const cancelled    = error.name === 'AbortError'
        // 명시적 errorCode를 우선하고, 코드가 없는 응답에서만 일부 상태코드를 보조 기준으로 삼는다.
        // 422가 항상 입력 오류는 아니다. 서버가 AI_BLOCKED를 주면 그 코드가 그대로 우선한다.
        const code         = error.errorCode || { 422: 'INVALID_INPUT', 504: 'AI_TIMEOUT' }[error.status]
        const unauthorized = code === 'UNAUTHORIZED' || error.status === 401
        if (unauthorized) clearAuth(request.token)
        else retryRoom = { id: current.id, title: current.title, question }

        setStatus(
            cancelled ? '응답 대기를 중지했어요. 입력한 질문은 남겨두었습니다.' : error.message || '응답을 받지 못했어요. 다시 시도해 주세요.',
            cancelled ? 'info' : 'error',
            {
                requestId : error.requestId,
                // 시간 초과에만 재시도 버튼을 제공한다. 실제 재전송은 사용자가 누를 때 발생한다.
                retry     : !unauthorized && ['AI_TIMEOUT', 'CLIENT_TIMEOUT'].includes(code),
                login     : unauthorized && !auth
            }
        )
        if (unauthorized && !auth) openLogin()
        if (code === 'INVALID_INPUT') $('.question').setAttribute('aria-invalid', 'true')
    } finally {
        // 완료된 과거 요청이 새 요청의 잠금을 해제하지 않도록 마지막 정리도 동일성 검사 후 수행한다.
        // 인증 이벤트가 이미 pending을 비웠다면 계정 전환 쪽 render가 화면 정리를 맡는다.
        if (pending === request) {
            pending = null
            render()
            if (!$('.auth-dialog').open) $('.question').focus()
        }
    }
}

