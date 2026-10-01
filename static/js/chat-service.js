import { client } from './client.js'

export const MAX_CHATS = 30

const errors = {
    401       : '로그인이 필요합니다. 다시 로그인해 주세요.',
    404       : '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    405       : '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    422       : '질문 내용을 확인해 주세요. 질문은 5,000자 이내로 입력해 주세요.',
    429       : '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
    default   : '서버 오류로 응답을 받지 못했습니다.',
    cancelled : '사용자가 중지했습니다.',
    timeout   : '응답 시간이 초과됐어요. 다시 시도해 주세요.',
}

// 질문과 방 정보를 서버로 보내고 응답을 반환한다.
export const request_chat = (question, room_id, room_name, token, signal) => client(
    '/api/chat', { question, room_id, room_name }, { token, signal, errors }
)

// 게스트와 로그인 사용자별 대화 저장 키를 만든다.
const storageKeyFor = id => 'damda-chat-v1' + (id ? `:user:${encodeURIComponent(id)}` : '')

// HTTP 환경에서도 사용할 수 있는 대화방 ID를 만든다.
export const uid = () => crypto.randomUUID?.() || Array.from(
    crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')
).join('')

// 잘린 이모지 등 올바르지 않은 문자를 교체한다.
const wellFormed = text => Array.from(text, character =>
    character.length === 1 && character >= '\uD800' && character <= '\uDFFF' ? '\uFFFD' : character
).join('')

// 저장된 대화의 방 정보와 메시지 형식을 확인한다.
const isValidChat = chat =>
    chat && typeof chat.id === 'string' && typeof chat.title === 'string' &&
    Array.isArray(chat.messages) && chat.messages.every(message =>
        message && ['user', 'assistant'].includes(message.role) && typeof message.text === 'string'
    )

// 사용자별 대화를 불러오고 이전에 잘못 저장된 제목을 복원한다.
export const loadChats = id => {
    try {
        const loaded = JSON.parse(localStorage.getItem(storageKeyFor(id)) || '[]')
        if (!Array.isArray(loaded)) return []

        return loaded.filter(isValidChat).slice(0, MAX_CHATS).map(chat => {
            if (!chat.title.trim() || Array.from(chat.title).length > 100 || wellFormed(chat.title) !== chat.title) {
                const question = chat.messages.find(message => message.role === 'user')?.text || '새로운 대화'
                chat.title = Array.from(wellFormed(question)).slice(0, 30).join('')
            }
            return chat
        })
    } catch { return [] }
}

// 사용자별 대화를 저장하고 저장 성공 여부를 반환한다.
export const saveChats = (id, chats) => {
    try   { localStorage.setItem(storageKeyFor(id), JSON.stringify(chats.slice(0, MAX_CHATS))) }
    catch { return false }
    return true
}
