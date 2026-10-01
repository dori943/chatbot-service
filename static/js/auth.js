// [DOM 요소 메모이제이션 저장소: elements]
// 반복적인 document.getElementById() DOM 트리 순회 비용을 제거하고 O(1) 조회를 보장하는 캐시 Map
const elements = new Map();

// ==============================================================================
// [로컬 스토리지 액세스 토큰 조회기: getAccessToken]
// 브라우저 localStorage에서 'access_token' 키를 안전하게 조회
// - 예외 격리: Safari 시크릿 모드나 쿠키/스토리지 차단 환경의 SecurityError 예외를 방어하여 null 반환
// ==============================================================================
export function getAccessToken() {
  // 브라우저 로컬 스토리지 접근 시도
  try {
    // 저장된 액세스 토큰 문자열 반환
    return localStorage.getItem('access_token');
  // 스토리지 접근 권한 거부 또는 보안 예외 발생 시 안전하게 격리
  } catch (_) {
    // 예외 발생 시 비인증 상태(null)로 폴백
    return null;
  }
}

// ==============================================================================
// [JWT 페이로드 클레임 디코더: getTokenClaims]
// JWT의 중간 페이로드 세그먼트를 추출하고 Base64URL 디코딩 및 UTF-8 역직렬화 수행
// 1) Base64URL 치환: URL-safe 문자('-', '_')를 표준 Base64 문자('+', '/')로 정규화
// 2) 다국어 바이트 복원: atob()의 한글/특수문자 깨짐(Mojibake)을 방지하기 위해 TextDecoder를 통한 UTF-8 디코딩
// 3) 보안 경계: 클라이언트는 서명 키(Secret)가 없으므로 표기 및 만료 확인용으로만 활용하며 위변조 검증은 백엔드 위임
// ==============================================================================
function getTokenClaims() {
  try {
    // Header.Payload.Signature 중 Payload 세그먼트(인덱스 1) 추출
    const payload = getAccessToken()?.split('.')[1];
    // 페이로드가 존재하지 않으면 즉시 종료
    if (!payload) return null;
    // JWT의 UTF-8 사용자 ID를 복원한다. 실제 서명 검증은 백엔드가 수행한다.
    const bytes = Uint8Array.from(atob(payload.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
    // UTF-8 디코더를 거쳐 완전한 JSON 문자열로 복원한 뒤 클레임 객체로 파싱
    const claims = JSON.parse(new TextDecoder().decode(bytes));
    // 파싱된 JWT 클레임 객체 반환
    return claims;
  // 토큰 형식이 손상되었거나 파싱 실패 시 예외 격리
  } catch (_) {
    // 유효하지 않은 클레임에 대해 null 반환
    return null;
  }
}

// ==============================================================================
// [인증 상태 및 사용자 식별자 판별기: getAuthenticatedId]
// 클라이언트의 로그인 유효성 및 활성 사용자 식별자를 판별하는 핵심 함수
// 1) 만료 검증: claims.exp 초 단위를 ms로 변환하여 Date.now()와 비교 (만료 시 null 반환)
// 2) 유효성 보장: 유효 기간 내의 정상적인 string 타입 사용자 ID만 반환
// ==============================================================================
export function getAuthenticatedId() {
  // 토큰 페이로드 클레임 조회
  const claims = getTokenClaims();
  // 만료 시각(exp)이 유효하지 않거나 현재 시각(ms)을 경과한 경우 만료 처리
  if (!Number.isFinite(claims?.exp) || claims.exp * 1000 <= Date.now()) return null;
  // 사용자 식별자(id)가 비어있지 않은 문자열인 경우 유효 ID 반환, 아니면 null 반환
  return typeof claims.id === 'string' && claims.id ? claims.id : null;
}

// ==============================================================================
// [지연 로딩 DOM 캐싱 헬퍼: getElement]
// elements Map을 조회하여 캐시된 DOM 요소가 없으면 getElementById를 수행 후 캐시에 적재
// ==============================================================================
function getElement(id) {
  // 캐시에 해당 ID의 요소가 없으면 DOM에서 조회하여 캐시에 등록
  if (!elements.has(id)) elements.set(id, document.getElementById(id));
  // 캐시된 DOM 요소 반환
  return elements.get(id);
}

// 인증 모달 모드 플래그: false는 로그인 모드, true는 회원가입 모드
let signup = false;
// 토큰 만료 스케줄링 타이머 식별자 (clearTimeout 및 메모리 누수 방지용)
let expiryTimer;

// ==============================================================================
// [인증 상태 기반 DOM 렌더러: renderAuthUI]
// getAuthenticatedId()의 유효성 검사 결과를 바탕으로 UI 요소들을 일괄 동적 치환
// 1) 헤더 사용자 식별자 노출 및 비인증 시 hidden 속성 적용
// 2) 로그인/로그아웃 버튼 텍스트 토글
// 3) 사이드바 아바타 텍스트(ID 첫 글자 vs 'G') 및 프로필 정보 갱신
// 4) 웹 접근성 aria-label 갱신으로 스크린 리더 음성 안내 지원
// ==============================================================================
function renderAuthUI() {
  // 인증된 사용자 식별자 조회 (유효하지 않으면 null)
  const id = getAuthenticatedId();
  // 로그인 여부 불리언 판정
  const loggedIn = Boolean(id);
  // 탑바 사용자 표시 영역 텍스트 주입
  getElement('header-user').textContent = id || '';
  // 로그인 상태에 따른 탑바 사용자 요소 표시/숨김 제어
  getElement('header-user').hidden = !loggedIn;
  // 탑바 인증 버튼 텍스트 전환
  document.querySelector('.login-button').textContent = loggedIn ? '로그아웃' : '로그인';
  // 사이드바 아바타 텍스트(로그인 시 ID 첫 글자 대문자, 비로그인 시 'G') 주입
  document.querySelector('.profile .avatar').textContent = loggedIn ? id[0].toUpperCase() : 'G';
  // 사이드바 프로필 사용자명 갱신
  document.querySelector('.profile strong').textContent = id || '게스트';
  // 사이드바 프로필 보조 텍스트 갱신
  document.querySelector('.profile small').textContent = loggedIn ? '로그아웃' : '로그인하여 이어가기';
  // 스크린 리더를 위한 접근성 레이블 동적 반영
  document.querySelector('.profile').setAttribute('aria-label', loggedIn ? `${id} 계정 로그아웃` : '로그인');
}

// ==============================================================================
// [인증 상태 변경 이벤트 브로드캐스터: notifyAuthChange]
// CustomEvent('authchange')를 브라우저 윈도우 객체에 디스패치
// - 옵저버 패턴: chat.js 등 타 모듈과의 결합도를 낮추고 인증 변경 시 대화 내역 동기화 트리거
// ==============================================================================
function notifyAuthChange() {
  // 전역 window에 authchange 커스텀 이벤트 발행 (detail에 현재 유저 ID 전달)
  window.dispatchEvent(new CustomEvent('authchange', { detail: { id: getAuthenticatedId() } }));
}

// ==============================================================================
// [인증 상태 동기화 및 자동 만료 스케줄러: syncAuthState]
// 로컬 스토리지 상태 검사, UI 렌더링, 이벤트 전파 및 토큰 만료 타이머를 일괄 제어
// 1) 토큰 무효화 정리: 토큰 문자열은 존재하나 만료/손상된 경우 localStorage에서 자동 제거
// 2) UI 및 이벤트 동기화: renderAuthUI() 및 notifyAuthChange() 순차 실행
// 3) 타이머 등록 (32비트 오버플로우 방어):
//    - setTimeout에 전달되는 딜레이 값이 32비트 부호 있는 정수 최댓값(2,147,483,647ms, 약 24.8일)을
//      초과할 경우 브라우저 정수 오버플로우로 인해 0ms(즉시 실행) 버그가 발생하는 것을 방지
// ==============================================================================
function syncAuthState() {
  // 기존 예약된 만료 타이머 해제
  clearTimeout(expiryTimer);
  // 토큰 문자열은 존재하지만 유효성 검사를 통과하지 못한 경우 스토리지에서 삭제
  if (getAccessToken() && !getAuthenticatedId()) localStorage.removeItem('access_token');
  // 변경된 상태에 맞추어 DOM UI 재렌더링
  renderAuthUI();
  // 타 컴포넌트(chat.js)에 상태 변경 이벤트 전파
  notifyAuthChange();
  // 토큰 만료 시점 스케줄링을 위한 클레임 재조회
  const claims = getTokenClaims();
  // 로그인 상태인 경우 만료 타이머 스케줄링
  if (getAuthenticatedId()) {
    // 만료 시각까지 남은 시간(ms) 계산 및 32비트 정수 오버플로우 방어 적용 후 타이머 설정
    expiryTimer = setTimeout(syncAuthState, Math.min(claims.exp * 1000 - Date.now(), 2_147_483_647));
  }
}

// ==============================================================================
// [경쟁 상태 방어 로그아웃 핸들러: clearAuth]
// 로컬 스토리지의 액세스 토큰을 제거하고 인증 상태를 비인증으로 동기화
// - 경쟁 상태(Race Condition / Stale Token Invalidation) 방어:
//   비동기 요청의 401 응답이 지연 도착했을 때, 사용자가 이미 새 계정으로 로그인한 상태라면
//   인자로 전달받은 토큰과 현재 저장소의 토큰이 불일치하므로 삭제를 건너뛰어 새 세션을 보호
// ==============================================================================
export function clearAuth(token = getAccessToken()) {
  // 이전 요청의 401이 새로 로그인한 토큰까지 삭제하지 않게 한다.
  if (token !== getAccessToken()) return;
  // 토큰이 존재하면 로컬 스토리지에서 제거
  if (token) localStorage.removeItem('access_token');
  // 인증 상태 전역 재동기화
  syncAuthState();
}

// ==============================================================================
// [인증 모달 인터랙션 및 폼 라이프사이클 이벤트 바인더: bindAuthEvents]
// 모달 다이얼로그 제어, 탭 스위칭, 폼 제출 가로채기(Event Interception) 및 Fetch 통신 바인딩
// 1) 트리거 분기: 인증 완료 시 즉시 로그아웃(clearAuth), 비인증 시 모달 오픈(showModal)
// 2) 다이얼로그 클린업: 닫힘(close) 이벤트 시 입력 필드(reset) 및 상태 메시지 초기화
// 3) 단일 폼 다중 모드 전환: 탭 클릭에 따라 속성 및 UI 동적 스위칭
// 4) 폼 제출 가로채기(preventDefault): 브라우저 기본 전송을 차단하고 비동기 AJAX 통신 수행
// ==============================================================================
function bindAuthEvents() {
  // 사이드바 프로필 및 탑바 로그인 버튼 등 data-auth 속성을 가진 모든 트리거 요소에 클릭 리스너 등록
  document.querySelectorAll('[data-auth]').forEach(button => button.addEventListener('click', () => {
    // 이미 로그인된 사용자인 경우 즉시 로그아웃 파이프라인 실행 후 조기 종료
    if (getAuthenticatedId()) {
      clearAuth();
      return;
    }
    // 이전 인증 상태 안내 문구 초기화
    getElement('auth-status').textContent = '';
    // HTML5 네이티브 모달 다이얼로그 오픈 (최상위 레이어 렌더링 및 백드롭 활성화)
    getElement('auth-dialog').showModal();
    // 사용자 편의성을 위해 아이디 입력 필드로 자동 포커스 이동
    getElement('auth-name').focus();
  }));
  // data-close 속성을 가진 모달 닫기 버튼 클릭 시 다이얼로그 닫기
  document.querySelector('[data-close]').addEventListener('click', () => getElement('auth-dialog').close());
  // 모달 다이얼로그 닫힘(close) 이벤트 발생 시 내부 상태 정리
  getElement('auth-dialog').addEventListener('close', () => {
    // 폼에 입력되어 있던 모든 사용자 입력 필드 초기화
    getElement('auth-form').reset();
    // 표시 중이던 상태 및 에러 메시지 초기화
    getElement('auth-status').textContent = '';
  });
  // 로그인 및 회원가입 모드 전환 탭 버튼(data-tab)에 클릭 리스너 등록
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
    // 클릭된 탭의 data-tab 속성이 'signup'인지 여부에 따라 모드 플래그 갱신
    signup = button.dataset.tab === 'signup';
    // 클릭된 탭 버튼에만 'active' 클래스를 부여하여 활성화 스타일 반영
    document.querySelectorAll('[data-tab]').forEach(tab => tab.classList.toggle('active', tab === button));
    // 선택된 모드에 따라 다이얼로그 상단 헤더 타이틀 동적 변경
    getElement('auth-title').textContent = signup ? '새로운 대화를 시작해요.' : '다시 만나 반가워요.';
    // 회원가입 모드일 때만 비밀번호 확인 컨테이너(#confirm-wrap) 표시
    getElement('confirm-wrap').hidden = !signup;
    // 회원가입 모드에서는 비밀번호 확인 입력을 필수(required)로 강제
    getElement('auth-confirm').required = signup;
    // 브라우저 자격 증명 관리 최적화: 회원가입 시 new-password, 로그인 시 current-password 지정
    getElement('auth-password').autocomplete = signup ? 'new-password' : 'current-password';
    // 활성화된 모드에 맞추어 폼 제출 버튼 텍스트 변경
    document.querySelector('.auth-submit').textContent = signup ? '회원가입' : '로그인';
    // 탭 전환 시 기존 에러/상태 안내 메시지 초기화
    getElement('auth-status').textContent = '';
  }));
  // ==============================================================================
  // [폼 제출 가로채기(Event Interception) 및 비동기 인증 파이프라인]
  // 1) 브라우저 기본 동작 가로채기 (event.preventDefault):
  //    - HTML <form>의 기본 제출 동작인 '페이지 전체 새로고침(Full Page Reload)'과 동기식 폼 전송을 원천 차단
  //    - 화면 깜빡임과 현재 대화 컨텍스트 유실을 방지하고, 모든 네트워크 통신을 비동기 Fetch API로 위임(SPA 코어 기술)
  // 2) 클라이언트 1차 방어선 (Client-Side Fail-Fast):
  //    - 회원가입 모드일 때 비밀번호와 비밀번호 확인 값의 일치 여부를 즉시 검증
  //    - 불일치 시 서버 통신 자체를 차단하고 조기 리턴하여 불필요한 네트워크 대역폭 및 백엔드 해싱 비용 방어
  // ==============================================================================
  getElement('auth-form').addEventListener('submit', async event => {
    // 브라우저의 기본 폼 제출 동작(페이지 새로고침 및 동기 전송)을 가로채어 비동기 제어권 확보
    event.preventDefault();
    // 아이디 입력 필드 값 추출
    const id = getElement('auth-name').value;
    // 비밀번호 입력 필드 값 추출
    const password = getElement('auth-password').value;
    // 상태 및 에러 메시지 렌더링 요소 참조
    const status = getElement('auth-status');

    // 회원가입 모드에서 비밀번호와 비밀번호 확인 값이 불일치하는 경우 선제적 차단
    if (signup && password !== getElement('auth-confirm').value) {
      // 불일치 안내 문구 표시
      status.textContent = '비밀번호가 서로 다릅니다.';
      // 백엔드 API 요청을 보내지 않고 즉시 함수 종료
      return;
    }

    // 모드 플래그에 따라 요청할 백엔드 API 엔드포인트 결정
    const endpoint = signup ? '/auth/register' : '/auth/login';

    try {
      // 백엔드 인증 엔드포인트로 JSON 페이로드 비동기 전송
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, pw: password })
      });
      // 백엔드 응답 본문 JSON 역직렬화
      const result = await response.json();

      // HTTP 응답 코드가 성공(200~299) 범위가 아닌 경우 에러 처리
      if (!response.ok) {
        // 백엔드 APIError 메시지를 상태 영역에 출력 (없으면 기본 실패 문구)
        status.textContent = typeof result.message === 'string' ? result.message : '요청에 실패했습니다.';
        return;
      }

      // 회원가입 성공 시 후속 처리
      if (signup) {
        // 성공 안내 메시지 표시 ("회원가입이 완료되었습니다.")
        status.textContent = result.message;
        // 비밀번호 필드만 초기화하고 아이디는 보존하여 로그인 편의성 제공
        getElement('auth-password').value = '';
        getElement('auth-confirm').value = '';
      // 로그인 성공 및 유효한 JWT 토큰 수신 시 후속 처리
      } else if (typeof result.token === 'string' && result.token) {
        // 발급받은 액세스 토큰을 로컬 스토리지에 영구 영속화
        localStorage.setItem('access_token', result.token);
        // 폼 입력 필드 전체 초기화
        getElement('auth-form').reset();
        // 모달 다이얼로그 닫기
        getElement('auth-dialog').close();
        // 전역 인증 상태 동기화 및 UI 갱신, authchange 이벤트 디스패치
        syncAuthState();
      // 토큰이 누락된 비정상 로그인 응답 처리
      } else {
        // 실패 메시지 노출
        status.textContent = result.message || '로그인에 실패했습니다.';
      }
    // 네트워크 단절 또는 서버 통신 실패 예외 처리
    } catch (error) {
      // 네트워크 장애 안내 메시지 노출
      status.textContent = '서버 연결에 실패했습니다.';
    }
  });
}

// 애플리케이션 초기 구동 시 로컬 스토리지 기반 인증 상태 동기화
syncAuthState();
// 모달 및 폼 인터랙션 이벤트 리스너 바인딩
bindAuthEvents();
// ==============================================================================
// [멀티 탭 동기화 및 브라우저 라이프사이클 이벤트 리스너]
// 1) storage 이벤트: 타 브라우저 탭/창에서 토큰이 변경(로그인/로그아웃)되었을 때 현재 탭 상태 즉시 동기화
// 2) focus & visibilitychange: 사용자가 다른 앱/창에서 작업 후 돌아왔을 때 토큰 만료 여부 재확인
// ==============================================================================
window.addEventListener('storage', event => {
  // access_token 키의 변경이 아닌 경우 무시
  if (event.key !== 'access_token') return;
  // 변경된 토큰 상태를 현재 탭의 UI에 즉각 반영
  syncAuthState();
});
// 브라우저 윈도우 포커스 획득 시 인증 상태 최신화
window.addEventListener('focus', syncAuthState);
// 문서 가시성 상태 변경(백그라운드 복귀) 시 활성화 상태라면 인증 동기화
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) syncAuthState();
});
