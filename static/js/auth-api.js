const REQUEST_TIMEOUT_MS = 30_000;

export async function requestAuthentication(signup, id, password, signal) {
  if (signal?.aborted) throw new DOMException('인증 요청을 취소했습니다.', 'AbortError');
  const controller = new AbortController();
  const abort = () => controller.abort();
  let timedOut = false;
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(signup ? '/auth/register' : '/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, pw: password }),
      signal: controller.signal,
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = result?.detail ?? result;
      const fallback = {
        401: '아이디 또는 비밀번호를 확인해 주세요.',
        409: '이미 사용 중인 아이디입니다.',
        422: '아이디와 비밀번호 입력을 확인해 주세요.',
        429: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
      };
      const error = new Error(typeof detail?.message === 'string' && detail.message
        || fallback[response.status] || '인증 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.');
      error.status = response.status;
      throw error;
    }
    if (!result || (signup ? typeof result.message !== 'string' : typeof result.token !== 'string' || !result.token)) {
      throw new Error('인증 응답을 확인할 수 없습니다. 다시 시도해 주세요.');
    }
    return result;
  } catch (error) {
    if (signal?.aborted) throw new DOMException('인증 요청을 취소했습니다.', 'AbortError');
    if (timedOut) throw new Error('인증 요청 시간이 초과됐습니다. 다시 시도해 주세요.');
    if (error instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 연결 상태를 확인해 주세요.');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
