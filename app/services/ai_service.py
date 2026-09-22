"""AI 호출 서비스 (Google Gemini).

설계 원칙
---------
1. 이 모듈은 DB / FastAPI / 요청 객체에 전혀 의존하지 않는다.
   - 최근 대화는 호출자(라우터)가 `history` 인자로 넘겨준다.
   - DB 저장은 라우터가 담당한다. 이 모듈은 결과 객체만 돌려준다.
   => 덕분에 백엔드 DB 작업과 무관하게 단독으로 개발/테스트가 가능하다.

2. `generate_answer()` 는 절대 예외를 밖으로 던지지 않는다.
   모든 실패는 AIResult(status="timeout"|"error") 로 변환된다.
   => AI API가 죽어도 서버는 살아 있는다. (미션 요구사항 5번)

3. 주 모델이 실패하면 폴백 모델로 한 번 더 시도한다.
   - 주:   AI_MODEL          (예: gemini-3.8-flash)
   - 폴백: AI_FALLBACK_MODEL (예: gemini-3.1-flash-lite)
   - 전체 소요 시간은 AI_TOTAL_TIMEOUT_SECONDS 로 상한을 둔다.
     폴백 때문에 사용자가 무한정 기다리는 일이 없도록 한다.

4. 모든 이벤트에 request_id 를 붙여 로그로 남긴다.
   => 서버 로그와 DB의 chat_logs.request_id 로 한 요청을 추적할 수 있다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Iterable

from google import genai
from google.genai import errors, types

from app.services.prompt import CONTEXT_TRUNCATED_NOTICE, SYSTEM_PROMPT

logger = logging.getLogger("app.ai")


# ---------------------------------------------------------------------------
# 설정 (환경 변수)
# ---------------------------------------------------------------------------
# NOTE: 백엔드에서 app/core/config.py 가 만들어지면 거기로 옮기고 import 만 바꾼다.

# NOTE: .env 에 키만 있고 값이 비어 있으면 os.getenv 는 기본값이 아니라 "" 를 준다.
#       `or` 로 받아야 빈 값일 때 기본 모델로 떨어진다.
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "").strip() or "gemini-3.8-flash"
AI_FALLBACK_MODEL = os.getenv("AI_FALLBACK_MODEL", "").strip() or "gemini-3.1-flash-lite"

AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "10"))
AI_TOTAL_TIMEOUT_SECONDS = float(os.getenv("AI_TOTAL_TIMEOUT_SECONDS", "24"))
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "1"))

AI_CONTEXT_TURNS = int(os.getenv("AI_CONTEXT_TURNS", "5"))
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "800"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.7"))

# Gemini 3.x 는 기본적으로 내부 추론(thinking)을 돌린다. gemini-3.8-flash 의 기본값은
# medium 이라 단순 Q&A 에도 응답이 7초 이상 걸리고, 추론 토큰만큼 비용도 늘어난다.
# 챗봇 용도에는 low 로 충분하다. 빈 문자열로 두면 모델 기본값을 그대로 쓴다.
AI_THINKING_LEVEL = os.getenv("AI_THINKING_LEVEL", "low").strip()

MAX_QUESTION_LENGTH = int(os.getenv("MAX_QUESTION_LENGTH", "5000"))

# 남은 전체 예산이 이보다 적으면 폴백을 시도하지 않는다 (어차피 못 끝낸다).
MIN_FALLBACK_BUDGET_SECONDS = 0.5
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))


# ---------------------------------------------------------------------------
# 에러 코드 / 사용자 안내 문구
# ---------------------------------------------------------------------------

class ErrorCode:
    TIMEOUT = "AI_TIMEOUT"
    RATE_LIMIT = "AI_RATE_LIMIT"
    UPSTREAM = "AI_UPSTREAM_ERROR"
    CONNECTION = "AI_CONNECTION_ERROR"
    BAD_REQUEST = "AI_BAD_REQUEST"       # 잘못된 모델명, 잘못된 파라미터 등
    BLOCKED = "AI_BLOCKED"               # 안전 필터에 의해 차단됨
    EMPTY_RESPONSE = "AI_EMPTY_RESPONSE"
    UNKNOWN = "AI_UNKNOWN_ERROR"
    INVALID_INPUT = "INVALID_INPUT"


USER_MESSAGES: dict[str, str] = {
    ErrorCode.TIMEOUT: "현재 응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.RATE_LIMIT: "요청이 많아 잠시 처리가 어려워요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.UPSTREAM: "AI 서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.CONNECTION: "AI 서비스에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.BAD_REQUEST: "요청을 처리할 수 없어요. 잠시 후 다시 시도해 주세요.",
    ErrorCode.BLOCKED: "이 질문에는 답변할 수 없어요. 다른 방식으로 질문해 주세요.",
    ErrorCode.EMPTY_RESPONSE: "답변을 생성하지 못했어요. 질문을 조금 바꿔서 다시 시도해 주세요.",
    ErrorCode.UNKNOWN: "일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
}

# 같은 모델로 한 번 더 시도해볼 만한 실패 (짧게 끝나는 실패들)
RETRY_SAME_MODEL = {ErrorCode.RATE_LIMIT, ErrorCode.CONNECTION}

# 폴백 모델로 넘어갈 만한 실패
# BLOCKED 는 제외 — 모델을 바꿔도 안전 필터 결과는 같으므로 시간만 낭비한다.
FALLBACK_TRIGGERS = {
    ErrorCode.TIMEOUT,
    ErrorCode.RATE_LIMIT,
    ErrorCode.UPSTREAM,
    ErrorCode.CONNECTION,
    ErrorCode.BAD_REQUEST,
    ErrorCode.EMPTY_RESPONSE,
    ErrorCode.UNKNOWN,
}


class QuestionValidationError(ValueError):
    """사용자 입력이 유효하지 않을 때. 이건 AI를 호출하기 전에 걸러낸다."""

    def __init__(self, message: str):
        super().__init__(message)
        self.error_code = ErrorCode.INVALID_INPUT
        self.message = message


# ---------------------------------------------------------------------------
# 결과 객체
# ---------------------------------------------------------------------------

@dataclass
class AIResult:
    """AI 호출 결과. 라우터는 이 객체를 그대로 chat_logs 에 저장하면 된다."""

    status: str                        # "success" | "timeout" | "error"
    request_id: str
    model: str                         # 실제로 응답을 만든(또는 마지막으로 시도한) 모델
    latency_ms: int
    answer: str | None = None
    error_code: str | None = None
    user_message: str | None = None    # 사용자에게 그대로 보여줄 안내 문구
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    fallback_used: bool = False        # 폴백 모델이 응답했는지

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    def to_log_row(self, user_id: str, question: str) -> dict[str, Any]:
        """chat_logs 테이블에 넣을 dict. 백엔드가 그대로 사용하면 된다.

        `model` 컬럼에 실제 사용된 모델이 들어가므로,
        폴백이 얼마나 자주 동작했는지 나중에 쿼리로 확인할 수 있다.
        """
        return {
            "user_id": user_id,
            "question": question,
            "answer": self.answer,
            "status": self.status,
            "error_code": self.error_code,
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "model": self.model,
        }


# ---------------------------------------------------------------------------
# 입력 검증 (미션 요구사항 5번: 입력 검증 최소 1개)
# ---------------------------------------------------------------------------

def validate_question(raw: str | None) -> str:
    """질문을 정규화하고 검증한다. 실패 시 QuestionValidationError."""
    if raw is None:
        raise QuestionValidationError("질문을 입력해 주세요.")

    question = raw.strip()

    if not question:
        raise QuestionValidationError("질문을 입력해 주세요.")

    if len(question) > MAX_QUESTION_LENGTH:
        raise QuestionValidationError(
            f"질문은 {MAX_QUESTION_LENGTH}자 이내로 입력해 주세요. "
            f"(현재 {len(question)}자)"
        )

    return question


# ---------------------------------------------------------------------------
# 컨텍스트 구성 (미션 요구사항 3번: 문맥 유지)
# ---------------------------------------------------------------------------

@dataclass
class PromptPayload:
    """Gemini 호출에 필요한 입력 묶음.

    Gemini는 시스템 프롬프트를 contents 가 아니라 config.system_instruction 으로
    따로 넘긴다. (OpenAI 처럼 messages[0] 에 넣지 않는다)
    """

    contents: list[dict[str, Any]] = field(default_factory=list)
    system_instruction: str = SYSTEM_PROMPT
    turns_used: int = 0
    truncated: bool = False


def build_contents(
    question: str,
    history: Iterable[dict[str, Any]] | None = None,
) -> PromptPayload:
    """Gemini contents 배열을 만든다.

    Parameters
    ----------
    question : 이번 질문 (검증을 마친 값)
    history  : 과거 대화. **오래된 것부터 시간순**으로 정렬된 리스트.
               각 항목은 {"question": str, "answer": str} 형태.
               반드시 status == "success" 인 행만 넘길 것.
               (실패한 대화가 섞이면 answer가 None이라 문맥이 깨진다)

    Notes
    -----
    - 역할 이름이 OpenAI와 다르다: assistant 가 아니라 **model** 이다.
    - 최근 AI_CONTEXT_TURNS 턴만 사용한다.
    - 전체 길이가 MAX_CONTEXT_CHARS 를 넘으면 오래된 턴부터 버린다.
    """
    turns: list[dict[str, Any]] = [
        t for t in (history or [])
        if t.get("question") and t.get("answer")
    ]
    turns = turns[-AI_CONTEXT_TURNS:]

    # 길이 예산 초과 시 오래된 턴부터 제거
    truncated = False
    while turns:
        total = sum(len(t["question"]) + len(t["answer"]) for t in turns)
        if total + len(question) <= MAX_CONTEXT_CHARS:
            break
        turns.pop(0)
        truncated = True

    contents: list[dict[str, Any]] = []
    for turn in turns:
        contents.append({"role": "user", "parts": [{"text": turn["question"]}]})
        contents.append({"role": "model", "parts": [{"text": turn["answer"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    system_instruction = SYSTEM_PROMPT
    if truncated:
        system_instruction = f"{SYSTEM_PROMPT}\n\n{CONTEXT_TRUNCATED_NOTICE}"

    return PromptPayload(
        contents=contents,
        system_instruction=system_instruction,
        turns_used=len(turns),
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Gemini 호출
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _client() -> genai.Client:
    """클라이언트는 한 번만 만들어 재사용한다 (커넥션 풀 유지)."""
    if not AI_API_KEY:
        raise RuntimeError(
            "AI_API_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요."
        )
    return genai.Client(api_key=AI_API_KEY)


def _classify(exc: Exception) -> str:
    """예외를 우리 에러 코드로 변환한다."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ErrorCode.TIMEOUT

    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        if code == 429:
            return ErrorCode.RATE_LIMIT
        if code in (400, 403, 404):
            return ErrorCode.BAD_REQUEST
        if isinstance(code, int) and code >= 500:
            return ErrorCode.UPSTREAM
        return ErrorCode.UPSTREAM

    # httpx 등 하위 라이브러리 예외는 이름으로 판별 (SDK 버전에 따라 타입이 바뀜)
    name = type(exc).__name__
    if "Timeout" in name:
        return ErrorCode.TIMEOUT
    if "Connect" in name or "Network" in name or "Transport" in name:
        return ErrorCode.CONNECTION
    return ErrorCode.UNKNOWN


def _extract_answer(response: Any) -> tuple[str, str | None]:
    """응답에서 텍스트를 꺼낸다. 실패 시 (빈 문자열, 에러코드)."""
    text = (getattr(response, "text", None) or "").strip()
    if text:
        return text, None

    # 안전 필터에 걸린 경우 prompt_feedback.block_reason 이 채워진다
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        return "", ErrorCode.BLOCKED

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        reason = str(getattr(candidates[0], "finish_reason", "") or "")
        if "SAFETY" in reason.upper() or "BLOCK" in reason.upper():
            return "", ErrorCode.BLOCKED

    return "", ErrorCode.EMPTY_RESPONSE


def _build_config(payload: PromptPayload, timeout: float) -> Any:
    """GenerateContentConfig 를 만든다.

    SDK 버전에 따라 지원하지 않는 옵션이 있을 수 있으므로,
    부가 옵션은 실패해도 기본 설정으로 넘어가도록 방어한다.
    """
    base = dict(
        system_instruction=payload.system_instruction,
        temperature=AI_TEMPERATURE,
        max_output_tokens=AI_MAX_TOKENS,
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # ms
    )
    extra: dict[str, Any] = {}

    # 함수 호출(AFC)은 쓰지 않는다 — 경고 제거 + 불필요한 왕복 방지
    try:
        extra["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            disable=True
        )
    except Exception:  # noqa: BLE001 - 구버전 SDK
        pass

    # 내부 추론 단계 낮추기 (응답 속도·비용 절감)
    if AI_THINKING_LEVEL:
        try:
            extra["thinking_config"] = types.ThinkingConfig(
                thinking_level=AI_THINKING_LEVEL
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "thinking_level=%s 를 이 SDK 버전이 지원하지 않아 무시합니다.",
                AI_THINKING_LEVEL,
            )

    try:
        return types.GenerateContentConfig(**base, **extra)
    except TypeError as exc:
        logger.warning("지원하지 않는 config 옵션이 있어 기본 설정으로 진행합니다: %s", exc)
        return types.GenerateContentConfig(**base)


async def _call_once(
    model: str,
    payload: PromptPayload,
    timeout: float,
) -> tuple[str | None, str | None, Any]:
    """모델을 한 번 호출한다. 반환: (answer, error_code, usage_metadata).

    asyncio.wait_for 로 타임아웃을 직접 강제한다.
    SDK 내부 타임아웃 동작에 의존하지 않기 위함이다.
    """
    config = _build_config(payload, timeout)

    response = await asyncio.wait_for(
        _client().aio.models.generate_content(
            model=model,
            contents=payload.contents,
            config=config,
        ),
        timeout=timeout,
    )

    text, err = _extract_answer(response)
    if err:
        return None, err, getattr(response, "usage_metadata", None)
    return text, None, getattr(response, "usage_metadata", None)


# ---------------------------------------------------------------------------
# 메인 진입점 (폴백 포함)
# ---------------------------------------------------------------------------

async def generate_answer(
    question: str,
    history: Iterable[dict[str, Any]] | None = None,
    *,
    user_id: str | None = None,
    request_id: str | None = None,
) -> AIResult:
    """질문 + 이전 대화로 AI 응답을 생성한다.

    흐름:
        주 모델 시도 → (일시적 실패면 1회 재시도) → 실패하면 폴백 모델 1회 시도

    이 함수는 **어떤 경우에도 예외를 던지지 않는다.**
    실패는 AIResult.status 로 표현되며, 라우터는 status 를 보고
    HTTP 상태코드와 사용자 안내 문구를 정하면 된다.
    """
    request_id = request_id or uuid.uuid4().hex[:12]
    payload = build_contents(question, history)

    candidates = [AI_MODEL]
    if AI_FALLBACK_MODEL and AI_FALLBACK_MODEL != AI_MODEL:
        candidates.append(AI_FALLBACK_MODEL)

    logger.info(
        "ai_call_start request_id=%s user_id=%s model=%s fallback=%s "
        "context_turns=%d q_len=%d",
        request_id, user_id, AI_MODEL, AI_FALLBACK_MODEL,
        payload.turns_used, len(question),
    )

    started = time.perf_counter()
    last_code = ErrorCode.UNKNOWN
    last_model = AI_MODEL
    fallback_attempted = False

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def remaining() -> float:
        return AI_TOTAL_TIMEOUT_SECONDS - (time.perf_counter() - started)

    for model_index, model in enumerate(candidates):
        is_fallback = model_index > 0
        last_model = model

        # 전체 예산이 거의 남지 않았으면 폴백을 포기한다 (사용자 대기 시간 보호).
        # 주 모델은 이 가드에서 제외한다. 주 모델까지 걸러버리면 한 번도 호출하지
        # 않은 채 last_code=UNKNOWN 으로 빠져나가 실패 원인이 사라진다.
        budget = min(AI_TIMEOUT_SECONDS, remaining())
        if is_fallback and budget <= MIN_FALLBACK_BUDGET_SECONDS:
            logger.warning(
                "ai_fallback_skip request_id=%s model=%s reason=no_time_budget",
                request_id, model,
            )
            break

        if is_fallback:
            fallback_attempted = True
            logger.warning(
                "ai_fallback_start request_id=%s from=%s to=%s cause=%s",
                request_id, candidates[0], model, last_code,
            )

        for attempt in range(AI_MAX_RETRIES + 1):
            try:
                answer, err_code, usage = await _call_once(model, payload, budget)

                if err_code is None:
                    logger.info(
                        "ai_call_success request_id=%s model=%s latency_ms=%d "
                        "attempt=%d fallback=%s a_len=%d",
                        request_id, model, elapsed_ms(), attempt + 1,
                        is_fallback, len(answer or ""),
                    )
                    return AIResult(
                        status="success",
                        request_id=request_id,
                        model=model,
                        latency_ms=elapsed_ms(),
                        answer=answer,
                        prompt_tokens=getattr(usage, "prompt_token_count", None),
                        completion_tokens=getattr(usage, "candidates_token_count", None),
                        fallback_used=is_fallback,
                    )

                last_code = err_code
                logger.warning(
                    "ai_call_fail request_id=%s model=%s error_code=%s attempt=%d",
                    request_id, model, err_code, attempt + 1,
                )

            except Exception as exc:  # noqa: BLE001 - 어떤 예외도 서버를 죽이지 않는다
                last_code = _classify(exc)
                logger.warning(
                    "ai_call_fail request_id=%s model=%s error_code=%s attempt=%d detail=%r",
                    request_id, model, last_code, attempt + 1, exc,
                )

            # 같은 모델로 재시도할지 판단
            can_retry = (
                last_code in RETRY_SAME_MODEL
                and attempt < AI_MAX_RETRIES
                and remaining() > 1.0
            )
            if not can_retry:
                break
            await asyncio.sleep(min(0.5 * (attempt + 1), max(0.0, remaining() - 0.5)))

        # 폴백으로 넘어갈 만한 실패가 아니면 여기서 종료
        if last_code not in FALLBACK_TRIGGERS:
            break

    status = "timeout" if last_code == ErrorCode.TIMEOUT else "error"
    logger.error(
        "ai_call_giveup request_id=%s model=%s error_code=%s latency_ms=%d fallback=%s",
        request_id, last_model, last_code, elapsed_ms(), fallback_attempted,
    )
    return AIResult(
        status=status,
        request_id=request_id,
        model=last_model,
        latency_ms=elapsed_ms(),
        error_code=last_code,
        user_message=USER_MESSAGES.get(last_code, USER_MESSAGES[ErrorCode.UNKNOWN]),
        fallback_used=fallback_attempted,
    )
