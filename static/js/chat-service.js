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

// 질문이 저장된 방 목록을 서버에서 불러온다.
export const request_rooms = async (token, signal) => {
    const { data } = await client('/api/me/rooms', undefined, { method: 'GET', token, signal, errors })
    return data.map(room => ({ id: room.room_id, title: room.room_name, messages: [] }))
}

// AI 오류와 서버 오류를 구분해 안내한다.
export const chatError = code => code?.startsWith('AI_')
    ? 'AI 응답을 받지 못했습니다. 잠시 후 다시 시도해 주세요.'
    : '서버 오류로 답변을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.'

// 선택한 방의 질문·답변·처리 상태를 오래된 순서로 불러온다.
export const request_history = async (room_id, token, signal) => {
    const { data } = await client(`/api/me/chats?room_id=${encodeURIComponent(room_id)}`, undefined, {
        method: 'GET', token, signal, errors,
    })
    return data.reverse().flatMap(row => [
        { id: row.id, role: 'user', text: row.question },
        {
            id: row.id, role: 'assistant', status: row.status,
            text: row.status === 'processing' ? '답변을 생성하고 있습니다…'
                : row.status === 'success' ? row.answer : chatError(row.error_code),
        },
    ])
}

// 선택한 방의 서버 대화 기록을 삭제한다.
export const request_delete_room = (room_id, token, signal) => client(
    `/api/me/chats?room_id=${encodeURIComponent(room_id)}`, undefined, { method: 'DELETE', token, signal, errors }
)

// 로그인 사용자별 방 목록 저장 키를 만든다.
const storageKeyFor = id => 'damda-chat-v1' + (id ? `:user:${encodeURIComponent(id)}` : '')

// HTTP 환경에서도 사용할 수 있는 대화방 ID를 만든다.
export const uid = () => crypto.randomUUID?.() || Array.from(
    crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')
).join('')

// 방 목록만 읽고 이전에 저장했던 메시지 본문은 제거한다.
export const loadRooms = id => {
    try {
        const loaded = JSON.parse(localStorage.getItem(storageKeyFor(id)) || '[]')
        if (!Array.isArray(loaded)) return []

        const rooms = loaded.filter(room => room && typeof room.id === 'string' && typeof room.title === 'string')
            .slice(0, MAX_CHATS).map(({ id, title }) => ({ id, title, messages: [] }))
        if (loaded.some(room => room?.messages)) saveRooms(id, rooms)
        return rooms
    } catch { return [] }
}

// 방 ID와 이름만 저장하고 질문·답변은 브라우저에 저장하지 않는다.
export const saveRooms = (id, rooms) => {
    try   { localStorage.setItem(storageKeyFor(id), JSON.stringify(rooms.slice(0, MAX_CHATS).map(({ id, title }) => ({ id, title })))) }
    catch { return false }
    return true
}
