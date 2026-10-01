import { client } from './client.js';

const ERROR_MESSAGES = {
  401: '로그인이 필요합니다. 다시 로그인해 주세요.',
  404: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  405: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  422: '질문 내용을 확인해 주세요. 질문은 5,000자 이내로 입력해 주세요.',
  429: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
  default: '서버 오류로 응답을 받지 못했습니다.',
  cancelled: '사용자가 중지했습니다.',
  timeout: '응답 시간이 초과됐어요. 다시 시도해 주세요.',
};

export async function requestReply(question, roomId, roomName, token, signal) {
  if (!token) throw new Error('로그인 후 질문을 보내 주세요.');
  const { data, requestId } = await client(
    '/api/chat',
    { question, room_id: roomId, room_name: roomName },
    { token, signal, errors: ERROR_MESSAGES },
  );
  if (typeof data?.answer !== 'string' || !data.answer.trim()) {
    const error = new Error('답변을 불러오지 못했습니다. 다시 시도해 주세요.');
    error.errorCode = 'INVALID_RESPONSE';
    error.requestId = requestId;
    throw error;
  }
  return data.answer;
}
