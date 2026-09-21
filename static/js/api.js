const REQUEST_TIMEOUT_MS = 30_000;

// 채팅 요청과 응답 검증, 취소 및 시간 초과를 처리합니다.
export async function requestReply(question, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  let timedOut = false;
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, {
    once: true
  });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      credentials: 'same-origin',
      body: JSON.stringify({
        question
      }),
      signal: controller.signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data?.detail ?? data;
      const message = typeof detail?.message === 'string' ? detail.message : null;
      const fallback = {
        401: '로그인이 필요합니다. 다시 로그인해 주세요.',
        404: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
        405: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
        422: '질문 내용을 확인해 주세요. 질문은 1,000자 이내로 입력해 주세요.',
        429: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
      };
      throw new Error(message || fallback[response.status] || '서버 오류로 응답을 받지 못했습니다.');
    }
    if (typeof data?.answer !== 'string' || !data.answer.trim()) {
      throw new Error('답변을 불러오지 못했습니다. 다시 시도해 주세요.');
    }
    return data.answer;
  } catch (error) {
    if (signal?.aborted) throw new DOMException('사용자가 중지했습니다.', 'AbortError');
    if (timedOut) throw new Error('응답 시간이 초과됐어요. 다시 시도해 주세요.');
    if (error instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 연결 상태를 확인해 주세요.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
