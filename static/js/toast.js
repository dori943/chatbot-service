const $ = selector => document.querySelector(selector)

let timer = null

// 안내를 표시하고 지정한 시간이 지나면 숨긴다. 0이면 계속 표시한다.
export const toast = (text, duration = 3000) => {
    clearTimeout(timer)
    $('.toast').textContent = text
    $('.toast').hidden      = false
    if (duration) timer = setTimeout(() => $('.toast').hidden = true, duration)
}
