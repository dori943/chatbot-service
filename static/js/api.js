/* 백엔드 요청을 담당하는 모듈입니다. DOM이나 화면 상태를 직접 변경하지 않습니다.
   현재는 서버 연결 전 데모 응답을 반환합니다. 실제 연동 시 이 함수를 FastAPI 요청으로 교체합니다.
   AI 제공사 API 키는 프론트엔드에 넣지 않습니다. */

export async function requestReply(message, signal) {
  await new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, 850);
    signal.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new DOMException('중지', 'AbortError'));
    }, {
      once: true
    });
  });
  if (message.includes('계획')) return '[미리보기 예시]\n일주일을 다음처럼 나누면 시작하기 편해요.\n\n월요일 — 목표와 핵심 기능 합의\n화·수요일 — 역할별 기능 구현\n목요일 — 화면과 API 연결\n금요일 — 오류 수정과 첫 배포\n\n매일 짧게 진행 상황을 공유하고, 큰 기능보다 끝낼 수 있는 작은 작업부터 진행해 보세요.\n\n실제 AI에 연결하면 질문에 맞춘 답변이 이 자리에 표시됩니다.';
  if (message.includes('리스트')) return '[미리보기 예시]\n리스트와 튜플은 여러 값을 순서대로 담습니다.\n\n리스트: [1, 2, 3] — 항목을 추가하거나 바꿀 수 있어요.\n튜플: (1, 2, 3) — 생성한 뒤 항목 자체를 바꿀 수 없어요.\n\n이 응답은 화면을 확인하기 위한 고정된 예시입니다. 실제 AI 연결은 백엔드에서 진행합니다.';
  if (message.includes('인사말')) return '[미리보기 예시]\n“안녕하세요. 오늘은 작은 아이디어가 하나의 서비스가 되기까지의 과정을 소개하려고 합니다. 저희가 어떤 문제를 발견하고, 어떻게 해결했는지 함께 살펴봐 주세요.”\n\n이런 느낌으로 대화가 표시됩니다. 실제 답변 생성은 백엔드 연결 후 사용할 수 있어요.';
  return '[미리보기 예시]\n질문을 잘 받았어요.\n\n“' + message.slice(0, 180) + '”\n\n이 화면은 디자인과 사용자 흐름을 비교하는 프론트엔드 예시입니다. 질문 전송, 대화 기록, 새 대화와 복사 기능을 직접 눌러볼 수 있어요.\n\n실제 AI API에 연결하면 이 위치에 모델의 답변이 나타납니다.';
}
