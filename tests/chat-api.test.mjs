import assert from 'node:assert/strict';
import { test } from 'node:test';
import { requestReply } from '../static/js/chat-api.js';

test('로그인 토큰과 질문을 전송하고 답변을 반환한다', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/chat');
    assert.equal(options.headers.Authorization, 'Bearer login-token');
    assert.deepEqual(JSON.parse(options.body), { question: '안녕' });
    return Response.json({ answer: '안녕하세요' });
  });
  assert.equal(await requestReply('안녕', 'login-token'), '안녕하세요');
});

test('토큰이 없거나 이미 취소된 요청은 전송하지 않는다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(requestReply('hi', null), /로그인/);
  await assert.rejects(requestReply('hi', 'token', AbortSignal.abort()), { name: 'AbortError' });
  assert.equal(fetch.mock.callCount(), 0);
});

for (const status of [401, 422, 429, 502, 503, 504]) {
  test(`${status} 오류 안내를 표시한다`, async t => {
    t.mock.method(globalThis, 'fetch', async () => Response.json(
      { error_code: 'TEST_ERROR', message: '테스트 오류 안내' }, { status },
    ));
    await assert.rejects(requestReply('hi', 'token'), /테스트 오류 안내/);
  });
}

test('JSON이 아닌 오류와 잘못된 성공 응답을 처리한다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('unavailable', { status: 503 }));
  await assert.rejects(requestReply('hi', 'token'), /서버 오류/);
  fetch.mock.mockImplementation(async () => Response.json({ answer: '' }));
  await assert.rejects(requestReply('hi', 'token'), /답변을 불러오지 못했습니다/);
});

test('사용자 중지 시 HTTP 요청을 취소한다', async t => {
  t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const controller = new AbortController();
  const result = requestReply('hi', 'token', controller.signal);
  controller.abort();
  await assert.rejects(result, { name: 'AbortError' });
});

test('시간 초과 안내와 네트워크 오류 안내를 구분한다', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const fetch = t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const result = requestReply('hi', 'token');
  t.mock.timers.tick(30_000);
  await assert.rejects(result, /응답 시간이 초과/);
  fetch.mock.mockImplementation(async () => { throw new TypeError('network'); });
  await assert.rejects(requestReply('hi', 'token'), /서버에 연결할 수 없습니다/);
});
