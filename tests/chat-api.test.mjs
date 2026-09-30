import assert from 'node:assert/strict';
import { test } from 'node:test';
import { requestReply } from '../static/js/chat-api.js';

test('로그인 토큰과 질문을 전송하고 답변을 반환한다', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/chat');
    assert.equal(options.headers.Authorization, 'Bearer login-token');
    assert.deepEqual(JSON.parse(options.body), { room_id: 'room-a', room_name: 'Test room', question: '안녕' });
    return Response.json({ answer: '안녕하세요' });
  });
  assert.equal(await requestReply('안녕', 'room-a', 'Test room', 'login-token'), '안녕하세요');
});

test('토큰이 없거나 이미 취소된 요청은 전송하지 않는다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', null), /로그인/);
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token', AbortSignal.abort()), { name: 'AbortError' });
  assert.equal(fetch.mock.callCount(), 0);
});

for (const status of [401, 422, 429, 502, 503, 504]) {
  test(`${status} 오류 안내를 표시한다`, async t => {
    t.mock.method(globalThis, 'fetch', async () => Response.json(
      { error_code: 'TEST_ERROR', message: '테스트 오류 안내', request_id: 'request-123' }, { status },
    ));
    await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token'), {
      message: '테스트 오류 안내', status, errorCode: 'TEST_ERROR', requestId: 'request-123',
    });
  });
}

test('JSON이 아닌 오류와 잘못된 성공 응답을 처리한다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('unavailable', { status: 503 }));
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token'), /서버 오류/);
  fetch.mock.mockImplementation(async () => Response.json({ answer: '' }));
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token'), /답변을 불러오지 못했습니다/);
});

test('사용자 중지 시 HTTP 요청을 취소한다', async t => {
  t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const controller = new AbortController();
  const result = requestReply('hi', 'room-a', 'Test room', 'token', controller.signal);
  controller.abort();
  await assert.rejects(result, { name: 'AbortError' });
});

test('시간 초과 안내와 네트워크 오류 안내를 구분한다', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const fetch = t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const result = requestReply('hi', 'room-a', 'Test room', 'token');
  t.mock.timers.tick(30_000);
  await assert.rejects(result, { message: '응답 시간이 초과됐어요. 다시 시도해 주세요.', errorCode: 'CLIENT_TIMEOUT' });
  fetch.mock.mockImplementation(async () => { throw new TypeError('network'); });
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token'), /서버에 연결할 수 없습니다/);
});

test('서버의 시간 초과 메시지와 오류 코드를 그대로 전달한다', async t => {
  const message = '현재 응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.';
  t.mock.method(globalThis, 'fetch', async () => Response.json(
    { error_code: 'AI_TIMEOUT', message, request_id: 'timeout-123' }, { status: 504 },
  ));
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token'), {
    message, status: 504, errorCode: 'AI_TIMEOUT', requestId: 'timeout-123',
  });
});

test('detail 오류의 메타데이터와 헤더 요청 ID를 처리한다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(
    { detail: { message: '서버 안내', error_code: 'INVALID_INPUT', request_id: 'body-id' } },
    { status: 422, headers: { 'X-Request-ID': 'header-id' } },
  ));
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token'), {
    message: '서버 안내', errorCode: 'INVALID_INPUT', requestId: 'body-id',
  });
  fetch.mock.mockImplementation(async () => new Response('proxy error', {
    status: 503, headers: { 'X-Request-ID': 'header-id' },
  }));
  await assert.rejects(requestReply('hi', 'room-a', 'Test room', 'token'), {
    status: 503, errorCode: null, requestId: 'header-id',
  });
});

test('24초 후 성공한 폴백 응답은 프론트 타임아웃에 취소되지 않는다', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let signal;
  t.mock.method(globalThis, 'fetch', (url, options) => {
    signal = options.signal;
    return new Promise(resolve => setTimeout(() => resolve(Response.json({ answer: '폴백 답변' })), 24_000));
  });
  const reply = requestReply('hi', 'room-a', 'Test room', 'token');
  t.mock.timers.tick(24_000);
  assert.equal(await reply, '폴백 답변');
  t.mock.timers.tick(6_000);
  assert.equal(signal.aborted, false);
});

test('본문 읽기가 지연된 로컬 시간 초과에도 헤더 요청 ID를 유지한다', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  t.mock.method(globalThis, 'fetch', async (url, { signal }) => ({
    ok: true,
    headers: new Headers({ 'X-Request-ID': 'slow-body-id' }),
    json: () => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))),
  }));
  const reply = requestReply('hi', 'room-a', 'Test room', 'token');
  await Promise.resolve();
  t.mock.timers.tick(30_000);
  await assert.rejects(reply, { errorCode: 'CLIENT_TIMEOUT', requestId: 'slow-body-id' });
});
