// 화면 상태와 분리된 채팅 요청 처리. 토큰은 호출 시점의 로그인 계정에서 전달한다.
// 서버의 기본 AI 처리 예산 24초에 응답 전송 여유를 더한다.
const REQUEST_TIMEOUT_MS = 30_000;

export async function requestReply(question, roomId, roomName, token, signal) {
  if (!token) throw new Error('로그인 후 질문을 보내 주세요.');
  if (signal?.aborted) throw new DOMException('사용자가 중지했습니다.', 'AbortError');
  const controller = new AbortController();
  const abort = () => controller.abort();
  let timedOut = false;
  let requestId = null;
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      credentials: 'same-origin',
      body: JSON.stringify({ question, room_id: roomId, room_name: roomName }),
      signal: controller.signal,
    });
    requestId = response.headers?.get('X-Request-ID') || null;
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail ?? data;
      const message = typeof detail?.message === 'string' ? detail.message : null;
      const fallback = {
        401: '로그인이 필요합니다. 다시 로그인해 주세요.',
        404: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
        405: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
        422: '질문 내용을 확인해 주세요. 질문은 5,000자 이내로 입력해 주세요.',
        429: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
      };
      const error = new Error(message || fallback[response.status] || '서버 오류로 응답을 받지 못했습니다.');
      error.status = response.status;
      error.errorCode = typeof detail?.error_code === 'string' ? detail.error_code : null;
      error.requestId = typeof detail?.request_id === 'string' && detail.request_id || requestId;
      throw error;
    }
    if (typeof data?.answer !== 'string' || !data.answer.trim()) {
      const error = new Error('답변을 불러오지 못했습니다. 다시 시도해 주세요.');
      error.errorCode = 'INVALID_RESPONSE';
      error.requestId = requestId;
      throw error;
    }
    return data.answer;
  } catch (error) {
    if (signal?.aborted) throw new DOMException('사용자가 중지했습니다.', 'AbortError');
    if (timedOut) {
      const timeout = new Error('응답 시간이 초과됐어요. 다시 시도해 주세요.');
      timeout.errorCode = 'CLIENT_TIMEOUT';
      timeout.requestId = requestId;
      throw timeout;
    }
    if (error instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 연결 상태를 확인해 주세요.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
