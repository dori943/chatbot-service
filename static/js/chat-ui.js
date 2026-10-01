// ==============================================================================
// [채팅 화면의 이벤트 진입점: chat-ui.js]
// index.html이 로드하는 모듈. 이전 chat.js의 이벤트 연결을 맡고 실제 상태 변경은 chat-action에 위임한다.
// 사용자 여정: submit/Enter → handleSubmit → request_chat → client → 서버 → 액션 갱신 → render.
// authchange → switchChatOwner, 목록 클릭 → selectChat처럼 "어떤 입력이 어떤 동작을 부르는가"를 읽는 파일이다.
// 채팅 DOM 생성은 chat-room.js, 로컬 저장과 API 요청 계약은 chat-service.js에 있다.
// ==============================================================================
import { openLogin } from './auth-ui.js'
import { setDrawer, renderHistory, copyText } from './chat-room.js'
import {
    chats, activeId, pending, updateInput, render,
    newChat, deleteChat, selectChat, switchChatOwner, handleSubmit
} from './chat-action.js'

// chats·activeId·pending은 가져온 순간의 복사본이 아니라 export let의 live binding이다.
// 액션이 pending을 새 요청으로 바꾸면 아래 중지 버튼 리스너도 그 시점의 최신 pending을 읽는다.
const $  = selector => document.querySelector(selector)
const $$ = selector => document.querySelectorAll(selector)

// 채팅 입력·대화 선택·복사·삭제·계정 변경 이벤트를 연결한다.
const bindChatEvents = () => {
    $('.chat-form')  .addEventListener('submit', handleSubmit)
    $('.stop-button').addEventListener('click', () => pending?.controller.abort())
    // requestSubmit은 submit 이벤트 경로를 다시 통과한다. 재시도에서도 인증·입력 검사를 재사용한다.
    // 여기서는 자동 재시도하지 않는다. 사용자가 버튼을 눌러 새 HTTP 요청을 보내는 방식이다.
    $('.retry')      .addEventListener('click', () => $('.chat-form').requestSubmit())
    $('.reauth')     .addEventListener('click', openLogin)

    $('.question').addEventListener('input', () => {
        $('.question').removeAttribute('aria-invalid')
        updateInput()
    })
    $('.question').addEventListener('keydown', event => {
        // Enter만 전송하고 Shift+Enter는 줄바꿈, 한글 등 IME 조합 중 Enter는 입력 확정으로 남긴다.
        if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
        event.preventDefault()
        $('.chat-form').requestSubmit()
    })

    $$('[data-new]').forEach(button => button.addEventListener('click', newChat))
    $$('[data-prompt]').forEach(button => button.addEventListener('click', () => {
        if (pending) return
        $('.question').value = button.dataset.prompt
        updateInput()
        $('.question').focus()
    }))

    $('.history-search').addEventListener('input', () => renderHistory(chats, activeId, Boolean(pending)))
    // [이벤트 위임] 목록은 renderHistory 때마다 교체된다. 유지되는 부모에 리스너를 한 번 달아 둔다.
    // closest는 클릭한 요소부터 부모 방향으로 탐색해 data-room이 있는 버튼을 찾는다.
    $('.history-list').addEventListener('click', event => {
        const button = event.target.closest('[data-room]')
        if (button) selectChat(button.dataset.room)
    })

    // 메시지도 반복 렌더링되므로 부모에서 복사/삭제 클릭을 구분한다. 현재 액션의 pending 검사도 적용된다.
    $('.transcript').addEventListener('click', event => {
        if (event.target.closest('.delete-chat')) return deleteChat()
        if (event.target.closest('.copy-button')) copyText(event.target.closest('.message'))
    })

    $('.menu-button').addEventListener('click', () => setDrawer(!$('.sidebar').classList.contains('is-open')))
    $('.scrim')      .addEventListener('click', () => setDrawer(false))
    window.matchMedia('(max-width: 760px)').addEventListener('change', () => setDrawer(false))
    document.addEventListener('keydown', event => { if (event.key === 'Escape') setDrawer(false) })
    // 인증 모듈은 채팅 내부 배열을 직접 변경하지 않고 id와 전환 이유만 발행한다.
    // 채팅 액션이 이 이벤트를 받아 자기 요청 취소·계정별 저장소·초안 복원을 처리한다.
    window.addEventListener('authchange', event => switchChatOwner(event.detail.id, event.detail.reason))
}

// [초기 실행] import 의존성이 먼저 평가된 뒤 이벤트를 등록하고 최초 화면을 그린다.
// auth-ui는 자기 초기화를 수행하며, chat-action은 초기 auth 값을 읽어서 ownerId와 대화를 준비한다.
bindChatEvents()
render()
