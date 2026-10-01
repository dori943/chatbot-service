// ==============================================================================
// [채팅 API 비동기 네트워크 통신 모듈: chat-api.js]
// UI DOM 조작과 네트워크 I/O 책임을 완전히 분리(Separation of Concerns)한 통신 계층
// 1) 인증 주입: 호출 시점의 최신 JWT 액세스 토큰을 HTTP Authorization Bearer 헤더에 탑재
// 2) 2중 요청 취소(AbortController): 사용자 수동 중단 신호 및 30초 클라이언트 타임아웃 통합 관리
// 3) DTO 정합성: 백엔드 ChatRequest 스키마({ question, room_id, room_name })와 1:1 페이로드 직렬화
// 4) 방어적 에러 핸들링: HTTP 상태 코드(401, 422, 429 등)별 사용자 친화적 폴백 메시지 매핑
// 5) 리소스 클린업: finally 블록을 통한 타이머 해제 및 이벤트 리스너 제거(메모리 누수 방지)
// ==============================================================================

// 클라이언트 측 네트워크 요청 최대 대기 시간 상수 (30초)
const REQUEST_TIMEOUT_MS = 30_000;

// ==============================================================================
// [채팅 답변 비동기 요청기: requestReply]
// 백엔드 /api/chat 엔드포인트로 질문 데이터를 전송하고 AI 생성 답변을 수신
// - parameters:
//   - question: 사용자 입력 질문 문자열
//   - roomId: 세션 고유 식별자
//   - roomName: 대화방 명칭
//   - token: 인증용 JWT 액세스 토큰 문자열
//   - signal: 사용자 UI 중지 버튼 연동용 AbortSignal
// ==============================================================================
export async function requestReply(question, roomId, roomName, token, signal) {
  // 인증 토큰 누락 시 네트워크 호출 차단 (클라이언트 선제 검증)
  if (!token) throw new Error('로그인 후 질문을 보내 주세요.');
  // 이미 사용자가 중지 버튼을 누른 상태인 경우 즉시 취소 예외 발생
  if (signal?.aborted) throw new DOMException('사용자가 중지했습니다.', 'AbortError');
  // 복합 취소 제어를 위한 자체 AbortController 인스턴스 생성
  const controller = new AbortController();
  // 취소 전파 헬퍼 함수 정의
  const abort = () => controller.abort();
  // 타임아웃 발생 여부 추적 플래그
  let timedOut = false;
  // 외부 사용자 중지 신호 발생 시 내부 컨트롤러 취소 전파 리스너 1회 등록
  signal?.addEventListener('abort', abort, { once: true });
  // 클라이언트 측 타임아웃(30초) 타이머 등록
  const timer = setTimeout(() => {
    // 타임아웃 플래그 활성화
    timedOut = true;
    // 네트워크 Fetch 요청 강제 중단 신호 송출
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    // 백엔드 채팅 처리 엔드포인트로 비동기 HTTP POST 통신 수행
    const response = await fetch('/api/chat', {
      // HTTP 메서드 지정
      method: 'POST',
      // JSON 규격 지정 및 Bearer 토큰 탑재 (FastAPI get_token_id 의존성과 매핑)
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      // 동일 출처 요청 간 자격 증명 포함 정책
      credentials: 'same-origin',
      // 백엔드 ChatRequest Pydantic 모델 규격에 맞춘 JSON 페이로드 직렬화
      body: JSON.stringify({ question, room_id: roomId, room_name: roomName }),
      // 복합 취소 컨트롤러의 신호 전달
      signal: controller.signal,
    });
    // JSON 응답 본문 파싱 (파싱 실패 시 null로 안전 격리)
    const data = await response.json().catch(() => null);
    // HTTP 상태 코드가 실패(4xx, 5xx)인 경우 에러 처리
    if (!response.ok) {
      // 백엔드 예외 응답 규격(detail 또는 data 본문) 파싱
      const detail = data?.detail ?? data;
      // 에러 메시지 문자열 추출
      const message = typeof detail?.message === 'string' ? detail.message : null;
      // 상태 코드별 기본 사용자 안내 폴백 매핑 테이블
      const fallback = {
        // 미인증 / 토큰 만료
        401: '로그인이 필요합니다. 다시 로그인해 주세요.',
        // 엔드포인트 부재
        404: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
        // 허용되지 않은 HTTP 메서드
        405: '채팅 서비스를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
        // 입력값 유효성 검증 실패 (길이 초과 등)
        422: '질문 내용을 확인해 주세요. 질문은 5,000자 이내로 입력해 주세요.',
        // 속도 제한(Rate Limit) 초과
        429: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
      };
      // 백엔드 메시지 또는 상태 코드별 폴백 문구를 담은 Error 객체 생성
      const error = new Error(message || fallback[response.status] || '서버 오류로 응답을 받지 못했습니다.');
      // 상위 핸들러 분기를 위해 HTTP 상태 코드 주입
      error.status = response.status;
      // 에러 송출
      throw error;
    }
    // 응답 데이터에 answer 필드가 누락되었거나 공백인 경우 예외 발생
    if (typeof data?.answer !== 'string' || !data.answer.trim()) {
      throw new Error('답변을 불러오지 못했습니다. 다시 시도해 주세요.');
    }
    // 최종 검증된 AI 답변 텍스트 반환
    return data.answer;
  // 네트워크 장애, 타임아웃, 중단 등 예외 처리
  } catch (error) {
    // 사용자가 명시적으로 중지 버튼을 눌러 취소된 경우
    if (signal?.aborted) throw new DOMException('사용자가 중지했습니다.', 'AbortError');
    // 30초 대기 시간 초과로 강제 중단된 경우
    if (timedOut) throw new Error('응답 시간이 초과됐어요. 다시 시도해 주세요.');
    // 인터넷 단절 등 순수 네트워크 통신 불가 예외인 경우
    if (error instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 연결 상태를 확인해 주세요.');
    // 기타 비즈니스/HTTP 에러 상위 전파
    throw error;
  // 요청 성공/실패 여부와 관계없이 항상 자원 정리(Clean-up) 수행
  } finally {
    // 등록된 타임아웃 타이머 해제 (메모리 누수 방지)
    clearTimeout(timer);
    // 외부 중지 신호 이벤트 리스너 제거
    signal?.removeEventListener('abort', abort);
  }
}
