"""AI 서비스 단독 테스트 스크립트 (Google Gemini).

DB도, FastAPI도, 도커도 없이 ai_service.py 만 검증한다.
백엔드 작업이 끝나기 전에 AI 파이프라인을 완성하기 위한 도구.

실행:
    # 레포 루트에서
    pip install -r requirements.txt
    cp .env.example .env        # AI_API_KEY 채우기
    python scripts/ai_smoke_test.py

    # 특정 테스트만
    python scripts/ai_smoke_test.py context fallback

테스트 목록:
    basic      실제 API 호출 1회
    context    문맥 유지 ("내가 방금 뭘 물어봤지?")
    timeout    타임아웃 시 서버가 죽지 않는지
    validation 입력 검증
    limit      컨텍스트 길이 제한 (API 호출 없음)
    fallback   폴백 동작 (API 호출 없음 - 가짜 실패를 주입)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# 레포 루트를 import 경로에 추가 (python scripts/... 로 실행 가능하게)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("[warn] python-dotenv 미설치 — 환경 변수를 직접 export 하세요.\n")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(name)s  %(message)s",
)
# SDK / HTTP 라이브러리 로그가 우리 로그를 덮어써서 읽기 어려워지므로 낮춘다.
# (서버에서도 app/core/logging.py 에 같은 설정을 넣는 것을 권장)
for _noisy in ("httpx", "httpcore", "google_genai", "google.genai"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _banner(title: str) -> None:
    print(f"\n{'=' * 68}\n  {title}\n{'=' * 68}")


def _verdict(ok: bool, label: str) -> None:
    print(f"\n→ {label}: {'✅ PASS' if ok else '❌ FAIL'}")


# ---------------------------------------------------------------------------
# 1. 기본 호출  (실제 API 사용)
# ---------------------------------------------------------------------------
async def test_basic() -> None:
    from app.services import ai_service

    _banner("1. 기본 질문")
    print(f"주 모델: {ai_service.AI_MODEL} / 폴백: {ai_service.AI_FALLBACK_MODEL}")

    q = ai_service.validate_question("  Gemini API가 뭐야? 두 문장으로 설명해줘.  ")
    result = await ai_service.generate_answer(q, user_id=1)

    print(f"status        : {result.status}")
    print(f"model         : {result.model}")
    print(f"fallback_used : {result.fallback_used}")
    print(f"latency_ms    : {result.latency_ms}")
    print(f"tokens        : {result.prompt_tokens} + {result.completion_tokens}")
    print(f"answer        : {result.answer}")
    _verdict(result.is_success, "정상 응답")


# ---------------------------------------------------------------------------
# 2. 문맥 유지 (미션 테스트 케이스)  (실제 API 사용)
# ---------------------------------------------------------------------------
async def test_context() -> None:
    from app.services import ai_service

    _banner("2. 문맥 유지 — '내가 방금 뭘 물어봤지?'")

    # DB에서 가져왔다고 가정한 이전 대화 (오래된 것부터 시간순)
    history = [
        {"question": "파이썬 리스트랑 튜플 차이가 뭐야?",
         "answer": "리스트는 변경 가능하고 튜플은 변경 불가능합니다."},
        {"question": "FastAPI 배포는 어떻게 해?",
         "answer": "uvicorn으로 실행하고 Docker로 컨테이너화한 뒤 서버에 올립니다."},
    ]

    payload = ai_service.build_contents("내가 방금 뭘 물어봤지?", history)
    print(f"contents 개수 : {len(payload.contents)} (history {len(history)*2} + 질문 1)")
    print(f"roles         : {[c['role'] for c in payload.contents]}")

    result = await ai_service.generate_answer(
        "내가 방금 뭘 물어봤지?", history, user_id=1
    )
    print(f"answer        : {result.answer}")
    _verdict("배포" in (result.answer or ""), "이전 질문(배포)을 기억하는가")


# ---------------------------------------------------------------------------
# 3. 타임아웃 — 서버가 죽지 않아야 한다  (실제 API 사용)
# ---------------------------------------------------------------------------
async def test_timeout() -> None:
    _banner("3. 타임아웃 (강제) — 예외가 새어나오면 안 됨")

    os.environ["AI_TIMEOUT_SECONDS"] = "0.001"
    os.environ["AI_TOTAL_TIMEOUT_SECONDS"] = "0.5"
    os.environ["AI_MAX_RETRIES"] = "0"

    import importlib
    from app.services import ai_service
    importlib.reload(ai_service)

    result = await ai_service.generate_answer("긴 글을 요약해줘", user_id=1)

    print(f"status        : {result.status}")
    print(f"error_code    : {result.error_code}")
    print(f"fallback_used : {result.fallback_used}")
    print(f"user_message  : {result.user_message}")
    _verdict(
        result.status == "timeout" and result.error_code == "AI_TIMEOUT",
        "예외 없이 타임아웃으로 처리되었는가",
    )

    for k in ("AI_TIMEOUT_SECONDS", "AI_TOTAL_TIMEOUT_SECONDS", "AI_MAX_RETRIES"):
        os.environ.pop(k, None)
    importlib.reload(ai_service)


# ---------------------------------------------------------------------------
# 4. 입력 검증  (API 호출 없음)
# ---------------------------------------------------------------------------
async def test_validation() -> None:
    from app.services import ai_service

    _banner("4. 입력 검증")

    cases = [("빈 문자열", ""), ("공백만", "     "), ("None", None), ("초장문", "가" * 5000)]
    ok = True
    for label, value in cases:
        try:
            ai_service.validate_question(value)
            print(f"  {label:10s} → ❌ 통과되면 안 됨")
            ok = False
        except ai_service.QuestionValidationError as e:
            print(f"  {label:10s} → ✅ 차단: {e.message}")
    _verdict(ok, "모든 잘못된 입력이 차단되는가")


# ---------------------------------------------------------------------------
# 5. 컨텍스트 길이 제한  (API 호출 없음)
# ---------------------------------------------------------------------------
async def test_context_limit() -> None:
    from app.services import ai_service

    _banner("5. 컨텍스트 길이 제한")

    long_history = [{"question": "질문" * 500, "answer": "답변" * 500} for _ in range(10)]
    payload = ai_service.build_contents("짧은 질문", long_history)
    total = sum(len(c["parts"][0]["text"]) for c in payload.contents)

    print(f"  원본 히스토리 : 10턴")
    print(f"  사용된 턴     : {payload.turns_used}턴 (상한 {ai_service.AI_CONTEXT_TURNS})")
    print(f"  총 글자 수    : {total} (상한 {ai_service.MAX_CONTEXT_CHARS})")
    print(f"  잘림 표시     : {payload.truncated}")

    dirty = [
        {"question": "성공한 질문", "answer": "성공한 답변"},
        {"question": "타임아웃난 질문", "answer": None},
    ]
    texts = [c["parts"][0]["text"] for c in ai_service.build_contents("다음", dirty).contents]
    _verdict("타임아웃난 질문" not in texts, "answer=None 인 대화가 제외되는가")


# ---------------------------------------------------------------------------
# 6. 폴백 동작  (API 호출 없음 — 가짜 실패를 주입한다)
# ---------------------------------------------------------------------------
async def test_fallback() -> None:
    from app.services import ai_service as s
    from google.genai import errors

    _banner("6. 폴백 동작 (가짜 실패 주입)")

    primary, fallback = s.AI_MODEL, s.AI_FALLBACK_MODEL
    print(f"주={primary}  폴백={fallback}\n")

    original = s._call_once
    calls: list[str] = []

    class _Usage:
        prompt_token_count = 10
        candidates_token_count = 20

    def inject(behavior):
        async def _call(model, payload, timeout):
            calls.append(model)
            outcome = behavior(model)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        s._call_once = _call

    async def scenario(name, behavior, expect_status, expect_model=None, expect_calls=None):
        calls.clear()
        inject(behavior)
        r = await s.generate_answer("테스트", [{"question": "이전Q", "answer": "이전A"}])
        ok = r.status == expect_status
        if expect_model:
            ok = ok and r.model == expect_model
        if expect_calls is not None:
            ok = ok and len(calls) == expect_calls
        print(f"  {'✅' if ok else '❌'} {name:26s} status={r.status:7s} "
              f"model={r.model:22s} fallback={r.fallback_used} 호출={len(calls)}회")
        return ok

    ok_success = ("답변입니다", None, _Usage())
    results = []
    try:
        results.append(await scenario(
            "주 모델 성공", lambda m: ok_success, "success", primary, 1))
        results.append(await scenario(
            "주 타임아웃 → 폴백",
            lambda m: asyncio.TimeoutError() if m == primary else ok_success,
            "success", fallback))
        results.append(await scenario(
            "주 429 → 폴백",
            lambda m: errors.APIError(429, "quota") if m == primary else ok_success,
            "success", fallback))
        results.append(await scenario(
            "주 404(모델명 오타) → 폴백",
            lambda m: errors.APIError(404, "not found") if m == primary else ok_success,
            "success", fallback))
        results.append(await scenario(
            "둘 다 실패", lambda m: asyncio.TimeoutError(), "timeout"))
        results.append(await scenario(
            "안전필터 차단 → 폴백 안 함",
            lambda m: (None, s.ErrorCode.BLOCKED, None), "error", primary, 1))
        results.append(await scenario(
            "알 수 없는 예외", lambda m: ValueError("boom"), "error"))
    finally:
        s._call_once = original

    _verdict(all(results), "폴백 전략이 의도대로 동작하는가")


TESTS = {
    "basic": test_basic,
    "context": test_context,
    "timeout": test_timeout,
    "validation": test_validation,
    "limit": test_context_limit,
    "fallback": test_fallback,
}

# API 키 없이도 돌릴 수 있는 테스트
OFFLINE = {"validation", "limit", "fallback"}


async def main() -> None:
    selected = sys.argv[1:] or list(TESTS)

    if not os.getenv("AI_API_KEY"):
        skipped = [n for n in selected if n not in OFFLINE]
        if skipped:
            print(f"[info] AI_API_KEY 없음 — 실제 호출 테스트 건너뜀: {', '.join(skipped)}")
        selected = [n for n in selected if n in OFFLINE]

    for name in selected:
        fn = TESTS.get(name)
        if fn is None:
            print(f"[skip] 알 수 없는 테스트: {name}")
            continue
        try:
            await fn()
        except Exception as e:  # noqa: BLE001
            print(f"💥 {name} 에러: {type(e).__name__}: {e}")

    print("\n완료.\n")


if __name__ == "__main__":
    asyncio.run(main())