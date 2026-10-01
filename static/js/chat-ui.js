import { openLogin } from './auth-ui.js'
import { setDrawer, renderHistory, copyText } from './chat-room.js'
import {
    chats, activeId, pending, updateInput, render,
    newChat, deleteChat, selectChat, switchChatOwner, handleSubmit
} from './chat-action.js'

const $  = selector => document.querySelector(selector)
const $$ = selector => document.querySelectorAll(selector)

// 채팅 입력·대화 선택·복사·삭제·계정 변경 이벤트를 연결한다.
const bindChatEvents = () => {
    $('.chat-form')  .addEventListener('submit', handleSubmit)
    $('.stop-button').addEventListener('click', () => pending?.controller.abort())
    $('.retry')      .addEventListener('click', () => $('.chat-form').requestSubmit())
    $('.reauth')     .addEventListener('click', openLogin)

    $('.question').addEventListener('input', () => {
        $('.question').removeAttribute('aria-invalid')
        updateInput()
    })
    $('.question').addEventListener('keydown', event => {
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
    $('.history-list').addEventListener('click', event => {
        const button = event.target.closest('[data-room]')
        if (button) selectChat(button.dataset.room)
    })

    $('.transcript').addEventListener('click', event => {
        if (event.target.closest('.delete-chat')) return deleteChat()
        if (event.target.closest('.copy-button')) copyText(event.target.closest('.message'))
    })

    $('.menu-button').addEventListener('click', () => setDrawer(!$('.sidebar').classList.contains('is-open')))
    $('.scrim')      .addEventListener('click', () => setDrawer(false))
    document.addEventListener('keydown', event => { if (event.key === 'Escape') setDrawer(false) })
    window.addEventListener('authchange', event => switchChatOwner(event.detail.id, event.detail.reason))
}

bindChatEvents()
render()
