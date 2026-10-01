import assert from 'node:assert/strict';
import { test } from 'node:test';
import { request_auth, getTokenID, removeToken } from '../static/js/auth-service.js';

const storage = new Map();
globalThis.localStorage = {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value),
  removeItem: key => storage.delete(key),
};

const makeToken = claims => `header.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.signature`;

for (const signup of [false, true]) {
  test(`${signup ? '회원가입' : '로그인'} 요청은 토큰 없이 전송한다`, async t => {
    const result = { message: signup ? 'register success' : 'login success', token: 'auth-token', token_type: 'bearer' };
    t.mock.method(globalThis, 'fetch', async (url, options) => {
      assert.equal(url, signup ? '/auth/register' : '/auth/login');
      assert.equal(options.method, 'POST');
      assert.equal(options.headers.Authorization, undefined);
      assert.deepEqual(JSON.parse(options.body), { id: 'alice', pw: ' password ' });
      return Response.json(result);
    });
    const { data } = await request_auth(signup ? '/auth/register' : '/auth/login', 'alice', ' password ');
    assert.deepEqual(data, result);
  });
}

test('인증 오류의 서버 안내와 상태별 기본 안내를 전달한다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(
    { detail: { message: '서버 안내', error_code: 'INVALID_INPUT' } },
    { status: 422, headers: { 'X-Request-ID': 'auth-request' } },
  ));
  await assert.rejects(request_auth('/auth/login', 'alice', 'password'), {
    message: '서버 안내', status: 422, errorCode: 'INVALID_INPUT', requestId: 'auth-request',
  });
  for (const [status, message] of [
    [401, /아이디 또는 비밀번호/], [409, /이미 사용 중인 아이디/],
    [422, /아이디와 비밀번호 입력/], [429, /인증 서버 오류/], [503, /인증 서버 오류/],
  ]) {
    fetch.mock.mockImplementation(async () => new Response('proxy error', { status }));
    await assert.rejects(request_auth('/auth/login', 'alice', 'password'), { message, status, requestId: null });
  }
});

test('이미 취소된 인증 요청은 전송하지 않는다', async t => {
  const fetch = t.mock.method(globalThis, 'fetch');
  await assert.rejects(request_auth('/auth/login', 'alice', 'password', AbortSignal.abort()), {
    name: 'AbortError', message: '인증 요청을 취소했습니다.',
  });
  assert.equal(fetch.mock.callCount(), 0);
});

test('인증 요청 취소를 공통 클라이언트에 전달한다', async t => {
  t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const controller = new AbortController();
  const result = request_auth('/auth/login', 'alice', 'password', controller.signal);
  controller.abort();
  await assert.rejects(result, { name: 'AbortError', message: '인증 요청을 취소했습니다.' });
});

test('인증 시간 초과와 네트워크 오류의 안내를 유지한다', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const fetch = t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const result = request_auth('/auth/login', 'alice', 'password');
  t.mock.timers.tick(30_000);
  await assert.rejects(result, { message: '인증 요청 시간이 초과됐습니다. 다시 시도해 주세요.', errorCode: 'CLIENT_TIMEOUT' });
  fetch.mock.mockImplementation(async () => { throw new TypeError('network'); });
  await assert.rejects(request_auth('/auth/login', 'alice', 'password'), /서버에 연결할 수 없습니다/);
});

test('한글 ID를 복원하고 만료되거나 잘못된 토큰은 저장소에서 삭제한다', () => {
  storage.clear();
  assert.equal(getTokenID(), null);
  const exp = Math.floor(Date.now() / 1000) + 300;
  const claims = { id: '홍길동🙂', exp };
  const token = makeToken(claims);
  localStorage.setItem('access_token', token);
  assert.deepEqual(getTokenID(), claims);
  assert.equal(storage.get('access_token'), token);
  for (const invalid of ['', 'broken', 'header.!!!.signature', makeToken(null), makeToken({ exp }),
    makeToken({ id: 'alice', exp: exp - 600 }), makeToken({ id: 'alice' }),
    makeToken({ id: 'alice', exp: String(exp) }), makeToken({ id: '', exp }),
  ]) {
    localStorage.setItem('access_token', invalid);
    assert.equal(Boolean(getTokenID()), false);
    assert.equal(storage.has('access_token'), false);
  }
});

test('저장소에 접근할 수 없으면 로그인 정보를 반환하지 않는다', t => {
  storage.clear();
  t.mock.method(localStorage, 'getItem', () => { throw new Error('blocked'); });
  assert.equal(getTokenID(), null);
  assert.equal(storage.size, 0);
});

test('명시적인 로그아웃은 토큰을 삭제하고 저장소 삭제 실패는 호출부에 전달한다', t => {
  storage.clear();
  localStorage.setItem('access_token', 'old-token');
  removeToken();
  assert.equal(storage.has('access_token'), false);
  localStorage.setItem('access_token', makeToken({ id: 'alice', exp: 1 }));
  t.mock.method(localStorage, 'removeItem', () => { throw new Error('blocked'); });
  assert.throws(() => getTokenID(), /blocked/);
  assert.equal(storage.has('access_token'), true);
});
