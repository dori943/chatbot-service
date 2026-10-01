// ==============================================================================
// [인증·채팅이 함께 사용하는 짧은 안내창: toast.js]
// UI에서 toast('안내')를 호출하면 표시하고, 기본 3초 뒤 숨긴다. toast('안내', 0)은 계속 표시한다.
// 인증과 채팅이 타이머를 따로 가지면 이전 채팅 안내의 타이머가 새 인증 오류까지 숨길 수 있다.
// 같은 모듈의 timer를 공유하고 새 안내마다 이전 타이머를 취소하여 이 문제를 막는다.
// 화면의 상시 상태·재시도 영역(chat-room.setStatus)과는 다른 일시적인 알림이다.
// ==============================================================================

// $는 별도 라이브러리가 아닌 querySelector를 짧게 호출하기 위한 함수다.
const $ = selector => document.querySelector(selector)

// 함수 밖의 모듈 상태: 같은 페이지에서 이 모듈을 가져온 호출자들이 하나의 타이머를 공유한다.
let timer = null

// 안내를 표시하고 지정한 시간이 지나면 숨긴다. 0이면 계속 표시한다.
export const toast = (text, duration = 3000) => {
    // 이전 안내가 예약한 숨김 작업부터 취소한다. 새 안내의 표시 시간을 보호하기 위해서다.
    clearTimeout(timer)
    // HTML로 해석하지 않고 문자열로 표시한다. .toast 요소는 index.html이 제공한다.
    $('.toast').textContent = text
    $('.toast').hidden      = false
    // 0은 falsy이므로 새 타이머를 만들지 않는다. 기존 timer 변수에 남은 취소된 ID는 동작하지 않는다.
    if (duration) timer = setTimeout(() => $('.toast').hidden = true, duration)
}
