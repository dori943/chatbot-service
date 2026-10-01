import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MAX_CHATS, request_chat, request_rooms, request_history, request_delete_room, uid, loadRooms, saveRooms } from '../static/js/chat-service.js';

test('로그인 토큰과 질문을 전송하고 답변을 반환한다', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/chat');
    assert.equal(options.headers.Authorization, 'Bearer login-token');
    assert.deepEqual(JSON.parse(options.body), { room_id: 'room-a', room_name: 'Test room', question: '안녕' });
    return Response.json({ answer: '안녕하세요' });
  });
  assert.deepEqual(await request_chat('안녕', 'room-a', 'Test room', 'login-token'), { data: { answer: '안녕하세요' }, requestId: null });
});

test('이미 취소된 요청은 전송하지 않는다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(request_chat('hi', 'room-a', 'Test room', 'token', AbortSignal.abort()), { name: 'AbortError' });
  assert.equal(fetch.mock.callCount(), 0);
});

for (const status of [401, 422, 429, 502, 503, 504]) {
  test(`${status} 오류 안내를 표시한다`, async t => {
    t.mock.method(globalThis, 'fetch', async () => Response.json(
      { error_code: 'TEST_ERROR', message: '테스트 오류 안내', request_id: 'request-123' }, { status },
    ));
    await assert.rejects(request_chat('hi', 'room-a', 'Test room', 'token'), {
      message: '테스트 오류 안내', status, errorCode: 'TEST_ERROR', requestId: 'request-123',
    });
  });
}

test('JSON이 아닌 오류 응답을 처리한다', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('unavailable', { status: 503 }));
  await assert.rejects(request_chat('hi', 'room-a', 'Test room', 'token'), /서버 오류/);
});

test('사용자 중지 시 HTTP 요청을 취소한다', async t => {
  t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const controller = new AbortController();
  const result = request_chat('hi', 'room-a', 'Test room', 'token', controller.signal);
  controller.abort();
  await assert.rejects(result, { name: 'AbortError' });
});

test('시간 초과 안내와 네트워크 오류 안내를 구분한다', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const fetch = t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const result = request_chat('hi', 'room-a', 'Test room', 'token');
  t.mock.timers.tick(30_000);
  await assert.rejects(result, { message: '응답 시간이 초과됐어요. 다시 시도해 주세요.', errorCode: 'CLIENT_TIMEOUT' });
  fetch.mock.mockImplementation(async () => { throw new TypeError('network'); });
  await assert.rejects(request_chat('hi', 'room-a', 'Test room', 'token'), /서버에 연결할 수 없습니다/);
});

test('서버의 시간 초과 메시지와 오류 코드를 그대로 전달한다', async t => {
  const message = '현재 응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.';
  t.mock.method(globalThis, 'fetch', async () => Response.json(
    { error_code: 'AI_TIMEOUT', message, request_id: 'timeout-123' }, { status: 504 },
  ));
  await assert.rejects(request_chat('hi', 'room-a', 'Test room', 'token'), {
    message, status: 504, errorCode: 'AI_TIMEOUT', requestId: 'timeout-123',
  });
});

test('detail 오류의 메타데이터와 헤더 요청 ID를 처리한다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(
    { detail: { message: '서버 안내', error_code: 'INVALID_INPUT', request_id: 'body-id' } },
    { status: 422, headers: { 'X-Request-ID': 'header-id' } },
  ));
  await assert.rejects(request_chat('hi', 'room-a', 'Test room', 'token'), {
    message: '서버 안내', errorCode: 'INVALID_INPUT', requestId: 'body-id',
  });
  fetch.mock.mockImplementation(async () => new Response('proxy error', {
    status: 503, headers: { 'X-Request-ID': 'header-id' },
  }));
  await assert.rejects(request_chat('hi', 'room-a', 'Test room', 'token'), {
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
  const reply = request_chat('hi', 'room-a', 'Test room', 'token');
  t.mock.timers.tick(24_000);
  assert.equal((await reply).data.answer, '폴백 답변');
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
  const reply = request_chat('hi', 'room-a', 'Test room', 'token');
  await Promise.resolve();
  t.mock.timers.tick(30_000);
  await assert.rejects(reply, { errorCode: 'CLIENT_TIMEOUT', requestId: 'slow-body-id' });
});

const storage = new Map();
globalThis.localStorage = {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value),
};

test('계정별 방 목록만 저장하고 질문과 답변은 저장하지 않는다', () => {
  storage.clear();
  const chats = Array.from({ length: MAX_CHATS + 1 }, (_, index) => ({ id: String(index), title: `방 ${index}`, messages: [{ role: 'user', text: 'private-question' }] }));
  assert.equal(saveRooms('한글 사용자', chats), true);
  assert.deepEqual(loadRooms('한글 사용자'), chats.slice(0, MAX_CHATS).map(room => ({ ...room, messages: [] })));
  assert.deepEqual(loadRooms('another-user'), []);
  assert.deepEqual(loadRooms(null), []);
  assert.equal(saveRooms(null, [chats[0]]), true);
  assert.deepEqual(loadRooms(null), [{ ...chats[0], messages: [] }]);
  assert.equal(storage.has('damda-chat-v1:user:' + encodeURIComponent('한글 사용자')), true);
  assert.equal(storage.has('damda-chat-v1'), true);
  for (const value of storage.values()) assert.equal(value.includes('private-question'), false);
});

test('이전 저장 형식에서 본문을 제거하고 방 정보만 읽는다', () => {
  const saved = [
    null,
    { id: 'bad', title: 123 },
    { id: 'valid', title: '<b>기존 제목</b>', messages: [{ role: 'assistant', text: '답변' }] },
  ];
  storage.set('damda-chat-v1', JSON.stringify(saved));
  assert.deepEqual(loadRooms(null), [{ id: 'valid', title: '<b>기존 제목</b>', messages: [] }]);
  assert.deepEqual(JSON.parse(storage.get('damda-chat-v1')), [{ id: 'valid', title: '<b>기존 제목</b>' }]);
  for (const invalid of ['{', '{}', 'null']) {
    storage.set('damda-chat-v1', invalid);
    assert.deepEqual(loadRooms(null), []);
  }
});

test('저장소 접근 실패 시 읽기는 빈 목록, 쓰기는 실패를 반환한다', t => {
  t.mock.method(localStorage, 'getItem', () => { throw new Error('blocked'); });
  t.mock.method(localStorage, 'setItem', () => { throw new Error('blocked'); });
  assert.deepEqual(loadRooms('alice'), []);
  assert.equal(saveRooms('alice', []), false);
});

test('방 목록과 방별 기록은 인증된 GET 요청으로 매번 조회한다', async t => {
  const urls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    urls.push(url);
    assert.equal(options.method, 'GET');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.body, undefined);
    assert.equal(options.headers.Authorization, 'Bearer token');
    return Response.json(url === '/api/me/rooms'
      ? [{ room_id: 'room / 한글', room_name: '제목' }]
      : [{ question: '최근 질문', answer: '최근 답변' }, { question: '이전 질문', answer: '이전 답변' }]);
  });
  assert.deepEqual(await request_rooms('token'), [{ id: 'room / 한글', title: '제목', messages: [] }]);
  const messages = await request_history('room / 한글', 'token');
  assert.deepEqual(messages.map(message => message.text), ['이전 질문', '이전 답변', '최근 질문', '최근 답변']);
  await request_history('room / 한글', 'token');
  assert.equal(urls.length, 3);
  assert.equal(urls[1], '/api/me/chats?room_id=' + encodeURIComponent('room / 한글'));
});

test('방 삭제는 인증된 DELETE 요청으로 서버에 전달한다', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/me/chats?room_id=room-a');
    assert.equal(options.method, 'DELETE');
    assert.equal(options.body, undefined);
    assert.equal(options.headers.Authorization, 'Bearer token');
    return Response.json({ deleted: 3 });
  });
  assert.equal((await request_delete_room('room-a', 'token')).data.deleted, 3);
});

test('UUID API가 없어도 유효한 방 ID를 만든다', t => {
  t.mock.method(crypto, 'randomUUID', () => undefined);
  const first = uid();
  assert.match(first, /^[0-9a-f]{32}$/);
  assert.notEqual(uid(), first);
});
