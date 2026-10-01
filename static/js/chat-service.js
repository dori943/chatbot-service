// ==============================================================================
// [채팅 데이터 담당: chat-service.js]
// 이전 chat-api.js의 채팅 계약 + chat.js의 로컬 저장 기능을 모았다. DOM 조작은 없다.
// HTTP: request_chat → client → /api/chat. 성공 시 { data, requestId }를 액션에 돌려준다.
// 로컬 저장: loadChats/saveChats → localStorage. 서버 MySQL 저장과는 별도의 화면 기록이다.
// 따라서 로컬 저장 실패가 곧 서버 저장 실패라는 뜻은 아니고, 로컬 방 삭제도 DB 삭제가 아니다.
// ==============================================================================
import { client } from './client.js'

// 브라우저에 유지할 대화방 개수이며, AI에 보낼 문맥 5턴이나 서버 로그 개수 제한과 다르다.
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
// [API 계약] question·room_id·room_name은 ChatRequest의 필수 필드, user_id는 서버가 토큰에서 추출한다.
// 공통 client에 채팅 오류 문구를 주입한다. 실제 로그인 상태 확인은 chat-action.js와 서버에서 한다.
// 예전 requestReply()와 달리 여기서 answer 문자열을 추출·검사하지 않고 응답 객체를 전달한다.
export const request_chat = (question, room_id, room_name, token, signal) => client(
    '/api/chat', { question, room_id, room_name }, { token, signal, errors }
)

// 게스트와 로그인 사용자별 대화 저장 키를 만든다.
// encodeURIComponent는 ID를 키의 일부로 표현하기 위한 인코딩이다. 암호화나 권한 검사가 아니다.
const storageKeyFor = id => 'damda-chat-v1' + (id ? `:user:${encodeURIComponent(id)}` : '')

// HTTP 환경에서도 사용할 수 있는 대화방 ID를 만든다.
// randomUUID가 제공되면 사용하고, 없으면 난수 16바이트를 두 자리 16진수 문자열로 연결한다.
// padStart(2, '0')는 0~15도 00~0f처럼 자리 수를 유지한다. 방 ID는 인증용 토큰이 아니다.
export const uid = () => crypto.randomUUID?.() || Array.from(
    crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')
).join('')

// 잘린 이모지 등 올바르지 않은 문자를 교체한다.
// [UTF-16 학습] 일반적인 이모지는 코드 유닛 두 개(서로게이트 쌍)로 표현될 수 있다.
// Array.from은 정상 쌍을 함께 꺼낸다. 홀로 남은 서로게이트만 U+FFFD 대체 문자로 바꾼다.
const wellFormed = text => Array.from(text, character =>
    character.length === 1 && character >= '\uD800' && character <= '\uDFFF' ? '\uFFFD' : character
).join('')

// 저장된 대화의 방 정보와 메시지 형식을 확인한다.
// localStorage는 사용자가 바꾸거나 과거 버전 값이 남을 수 있으므로 JSON 파싱만으로 신뢰하지 않는다.
// every는 모든 메시지가 조건을 만족하는지 확인한다. 이 검사는 서버 접근 권한을 증명하지 않는다.
const isValidChat = chat =>
    chat && typeof chat.id === 'string' && typeof chat.title === 'string' &&
    Array.isArray(chat.messages) && chat.messages.every(message =>
        message && ['user', 'assistant'].includes(message.role) && typeof message.text === 'string'
    )

// 사용자별 대화를 불러오고 이전에 잘못 저장된 제목을 복원한다.
// [읽기 순서] 문자열 조회 → JSON.parse → 배열/항목 확인 → 최대 30방 → 잘못된 제목 복구.
// API에서 내려받는 함수가 아니므로 다른 기기의 MySQL 기록을 화면에 동기화하지 않는다.
export const loadChats = id => {
    try {
        const loaded = JSON.parse(localStorage.getItem(storageKeyFor(id)) || '[]')
        if (!Array.isArray(loaded)) return []

        return loaded.filter(isValidChat).slice(0, MAX_CHATS).map(chat => {
            // 빈 제목·100자 초과·잘린 문자에 한해 첫 사용자 질문으로 제목을 다시 만든다.
            // 앞 30개 코드 포인트를 쓰므로 UTF-16 코드 유닛 중간에서 이모지를 자르는 일을 피한다.
            if (!chat.title.trim() || Array.from(chat.title).length > 100 || wellFormed(chat.title) !== chat.title) {
                const question = chat.messages.find(message => message.role === 'user')?.text || '새로운 대화'
                chat.title = Array.from(wellFormed(question)).slice(0, 30).join('')
            }
            return chat
        })
    // 읽기·파싱 실패는 빈 목록으로 처리한다. 이때 원래 저장값을 직접 삭제하는 코드는 없다.
    } catch { return [] }
}

// 사용자별 대화를 저장하고 저장 성공 여부를 반환한다.
// 객체 배열은 JSON.stringify로 직렬화한다. 저장 용량·권한 오류는 false로 보고하고 안내는 액션에서 한다.
export const saveChats = (id, chats) => {
    try   { localStorage.setItem(storageKeyFor(id), JSON.stringify(chats.slice(0, MAX_CHATS))) }
    catch { return false }
    return true
}
