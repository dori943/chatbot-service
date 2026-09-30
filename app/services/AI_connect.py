import asyncio
import time
import uuid

from dataclasses         import dataclass, field
from functools           import lru_cache
from typing              import Any, Iterable
from google              import genai
from google.genai        import errors, types

from app.core.config     import (
    AI_API_KEY,
    AI_MODEL,
    AI_FALLBACK_MODEL,
    AI_TIMEOUT_SECONDS,
    AI_TOTAL_TIMEOUT_SECONDS,
    AI_MAX_RETRIES,
    AI_CONTEXT_TURNS,
    AI_MAX_TOKENS,
    AI_TEMPERATURE,
    AI_THINKING_LEVEL,
    MAX_CONTEXT_CHARS,
    MIN_FALLBACK_BUDGET_SECONDS,
)

from app.core.errors     import (
    ErrorCode,
    RETRY_SAME_MODEL,
    FALLBACK_TRIGGERS,
    USER_MESSAGES,
)
from app.core.logging    import log_event
from app.schemas.chat    import AIResult
from app.services.prompt import CONTEXT_TRUNCATED_NOTICE, SYSTEM_PROMPT


@dataclass
class PromptPayload:
    contents           : list[dict[str, Any]] = field(default_factory=list)
    system_instruction : str  = SYSTEM_PROMPT
    turns_used         : int  = 0
    truncated          : bool = False


# ==============================================================================
# [프롬프트 빌더: build_contents 핵심 아키텍처 및 자료구조 원리]
#
# 1. 5단계 파이프라인 흐름:
#    1) 필터링: 리스트 컴프리헨션으로 question/answer가 온전한 대화 턴만 추출
#    2) 슬라이싱: 음수 슬라이싱([-AI_CONTEXT_TURNS:])으로 최근 대화만 유지
#    3) FIFO 절삭: 글자 수가 MAX_CONTEXT_CHARS를 넘으면 pop(0)으로 오래된 대화부터 제거
#    4) 규격 포맷팅: user와 model 롤 기반 핑퐁 대화 구조 조립 후 맨 뒤에 현재 질문 추가
#    5) 동적 지침: 대화가 잘렸다면(truncated) 시스템 프롬프트에 경고 안내문 부착
#
# 2. 자료구조적 관점 (스택 vs 큐):
#    - 스택(LIFO, chat_db.py): DB에서 최근 대화를 뽑기 위해 ORDER BY id DESC LIMIT N으로 꺼낸 후,
#      파이썬 메모리에서 reversed()로 뒤집어 자연스러운 시간순 대화 복원
#    - 큐(FIFO, AI_connect.py): 프롬프트 글자 수 초과 시 pop(0)으로 가장 오래된 대화부터
#      순차 방출하여 최신 문맥을 보존하는 슬라이딩 윈도우(Sliding Window) 유지
#
# 3. SQL 성능 최적화 인사이트:
#    - 왜 처음부터 ASC를 쓰면 안 되는가?: 처음부터 ASC로 LIMIT을 걸면 가장 오래된 첫 5건이
#      조회되는 논리적 결함이 발생하므로, '가장 최근' 대화를 자르기 위해 반드시 DESC로 조회함
#    - 왜 DB 서브쿼리 대신 파이썬 reversed()인가?: DB 서브쿼리는 임시 테이블 2차 정렬 부하를
#      초래하므로, DB에서는 단순 단일 인덱스 스캔만 수행하고 파이썬 메모리에서 0.0001초 만에 뒤집는 최적화 적용
# ==============================================================================
def build_contents(
    # 사용자의 현재 질문 문자열
    question: str,
    # [호출 흐름: chat_db.get_history ➔ chat_main.chat ➔ AI_connect.generate_answer ➔ build_contents]
    # 자연스러운 대화 맥락 유지를 위해 '과거 ➔ 최신' 시간순으로 정렬되어 넘어온 이전 대화 턴 목록
    history: Iterable[dict[str, Any]] | None = None,
) -> PromptPayload:
    """성공한 대화를 오래된 순서로 받아 최근 턴과 길이 제한을 적용한다."""
    # [1단계 실제 작용 지점: 정상 대화 턴 선별 및 필터링]
    # -------------------------------------------------------------------------
    # ■ 리스트 컴프리헨션(List Comprehension)이란?
    #   - for 반복문과 if 조건문을 대괄호 [ ] 안에 압축하여 새 리스트를 생성하는 파이썬 고유 문법
    #   - 동일한 일반 코드(4줄):
    #       turns = []
    #       for t in (history or []):
    #           if t.get("question") and t.get("answer"):
    #               turns.append(t)
    #   - 장점: 코드 라인 수가 대폭 줄어들고, 파이썬 C 레벨 최적화로 일반 for문+append보다 약 20~30% 더 빠름
    #
    # ■ 자연스럽게 읽는 3단계 순서 (어순이 거꾸로 느껴질 땐 중간 ➔ 아래 ➔ 맨 앞 순으로 읽습니다):
    #   1) [중간] for t in (history or [])             : history에서 대화 턴(t)을 하나씩 꺼낸다.
    #      * 왜 'or []'가 붙었는가?: history가 None일 때 'for t in None'이 실행되면 TypeError(순회 불가)로 서버가 죽으므로,
    #        파이썬의 단락 평가(A가 None이면 뒤의 B 채택)를 이용해 빈 리스트([])를 대신 순회시키는 무결성 방어 코드
    #   2) [아래] if t.get("question") and t.get("answer"): 꺼낸 t에 질문과 답변이 둘 다 온전히 있는지 확인한다.
    #   3) [맨 앞] t                                   : 조건을 통과한 t만 최종 리스트의 원소로 채택한다!
    # -------------------------------------------------------------------------
    turns: list[dict[str, Any]] = [
        # [읽는 순서 1 & 3] history에서 꺼내고, 아래 검증을 통과했을 때 최종적으로 바구니에 담길 대화 턴(t)
        # 방어 기제: history가 None이면 'None or []' 연산으로 빈 리스트([])가 채택되어 TypeError 예외를 완벽 방어함
        t for t in (history or [])
        # [읽는 순서 2] 유효성 필터링: 질문(question)과 답변(answer)이 둘 다 존재하는 정상 턴만 통과 (누락/빈값은 자동 탈락)
        if t.get("question") and t.get("answer")
    ]
    # [2단계 실제 작용 지점: 최근 대화 슬라이싱]
    # 음수 인덱스 슬라이싱([-N:]): 리스트 맨 뒤에서부터 N개를 잘라내어 가장 최근 대화만 유지 (토큰 낭비 방지)
    # (예: 대화가 10개 있어도 AI_CONTEXT_TURNS가 5라면 가장 최근 5개만 남김)
    turns = turns[-AI_CONTEXT_TURNS:]

    # 글자 수 제한 초과로 인한 과거 대화 절삭 여부 플래그
    truncated = False
    # [3단계 실제 작용 지점: 큐(Queue, FIFO) 방식의 글자 수 절삭]
    # 전체 대화 텍스트 길이가 허용 한도(MAX_CONTEXT_CHARS) 이하가 될 때까지 오래된 대화부터 큐 방식으로 제거
    while turns:
        # 현재 남은 대화 턴들의 질문/답변 글자 수 총합 계산
        total = sum(len(t["question"]) + len(t["answer"]) for t in turns)
        # 과거 대화 총 글자 수 + 현재 질문 글자 수가 최대 허용한도 이내이면 루프 탈출
        if total + len(question) <= MAX_CONTEXT_CHARS:
            break
        # 한도 초과 시 가장 오래된 대화(0번 인덱스)를 먼저 꺼내 버림 (First-In First-Out, 큐 동작)
        turns.pop(0)
        # 문맥 절삭 플래그 활성화
        truncated = True

    # [4단계 실제 작용 지점: Gemini 규격 핑퐁 대화 포맷팅]
    # Google Gemini API가 요구하는 대화형 규격(User ➔ Model ➔ User 핑퐁 대화) 리스트 초기화 (빈 바구니 생성)
    contents: list[dict[str, Any]] = []
    # 정제된 과거 대화 턴들을 user(사용자 질문)와 model(AI 답변)의 역할(Role) 기반 메시지로 번갈아 추가
    for turn in turns:
        # 1) 사용자 과거 질문 추가
        contents.append({"role": "user" , "parts": [{"text": turn["question"]}]})
        # 2) AI 모델의 과거 답변 추가
        contents.append({"role": "model", "parts": [{"text": turn["answer"]}]})
    # 3) 대화 흐름의 맨 마지막에 현재 사용자의 신규 질문을 user 역할로 추가하여 문맥 완성
    contents.append({"role": "user", "parts": [{"text": question}]})

    # [5단계 실제 작용 지점: 동적 시스템 프롬프트 변경 및 최종 패키징]
    # 기본 시스템 지침(System Prompt) 할당 (AI의 역할/페르소나 지정)
    system_instruction = SYSTEM_PROMPT
    # 인과관계: 3단계 while 루프에서 대화가 잘렸는지(truncated=True) 계산이 끝난 후에만 경고문 부착 가능
    # 글자 수 한도로 인해 과거 대화가 잘려나간 경우, AI에게 문맥 생략 안내 문구(CONTEXT_TRUNCATED_NOTICE) 추가
    if truncated:
        system_instruction = f"{SYSTEM_PROMPT}\n\n{CONTEXT_TRUNCATED_NOTICE}"

    # 최종 조립된 프롬프트 페이로드(내용, 시스템 프롬프트, 사용된 턴 수, 절삭 여부) 반환
    return PromptPayload(
        # 조립된 다자간 대화 메시지 구조체 리스트
        contents           = contents,
        # 모델의 행동 및 답변 스타일을 통제하는 시스템 프롬프트
        system_instruction = system_instruction,
        # 문맥 구성에 실제로 사용된 대화 턴 수
        turns_used         = len(turns),
        # 글자 수 초과로 과거 대화가 잘렸는지 여부
        truncated          = truncated,
    )


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=AI_API_KEY)


def _classify(exc: Exception) -> str:
    """예외를 우리 에러 코드로 변환한다."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ErrorCode.TIMEOUT

    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        if code in (401, 403):
            return ErrorCode.CONFIG
        if code == 400:
            # 키 오류는 HTTP 400의 구조화된 reason으로도 반환된다.
            details = getattr(exc, "details", {})
            if isinstance(details, dict):
                error = details.get("error", details)
                if isinstance(error, dict):
                    for detail in error.get("details", []) or []:
                        if isinstance(detail, dict) and str(detail.get("reason", "")).startswith("API_KEY_"):
                            return ErrorCode.CONFIG
            if "api key" in str(getattr(exc, "message", "") or "").lower():
                return ErrorCode.CONFIG
        if code == 429:
            return ErrorCode.RATE_LIMIT
        if code in (400, 404):
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
    # 안전 필터에 걸린 경우 prompt_feedback.block_reason 이 채워진다
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        return "", ErrorCode.BLOCKED

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        reason = str(getattr(candidates[0], "finish_reason", "") or "")
        if "MAX_TOKENS" in reason.upper():
            return "", ErrorCode.TOKEN_LIMIT
        if "SAFETY" in reason.upper() or "BLOCK" in reason.upper():
            return "", ErrorCode.BLOCKED

    text = (getattr(response, "text", None) or "").strip()
    if text:
        return text, None
    return "", ErrorCode.EMPTY_RESPONSE


def _build_config(payload: PromptPayload, timeout: float) -> Any:
    """GenerateContentConfig 를 만든다.

    SDK 버전에 따라 지원하지 않는 옵션이 있을 수 있으므로,
    부가 옵션은 실패해도 기본 설정으로 넘어가도록 방어한다.
    """
    base = dict(
        system_instruction = payload.system_instruction,
        temperature        = AI_TEMPERATURE,
        max_output_tokens  = AI_MAX_TOKENS,
        http_options       = types.HttpOptions(timeout=int(timeout * 1000)),  # ms
    )
    extra: dict[str, Any] = {}

    # 함수 호출(AFC)은 쓰지 않는다 — 경고 제거 + 불필요한 왕복 방지
    try:
        extra["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            disable = True
        )
    except Exception:  # noqa: BLE001 - 구버전 SDK
        pass

    # 내부 추론 단계 낮추기 (응답 속도·비용 절감)
    if AI_THINKING_LEVEL:
        try:
            extra["thinking_config"] = types.ThinkingConfig(
                thinking_level = AI_THINKING_LEVEL
            )
        except Exception:  # noqa: BLE001
            log_event("ai_config_option_ignored")

    try:
        return types.GenerateContentConfig(**base, **extra)
    except TypeError:
        log_event("ai_config_fallback")
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
    if not AI_API_KEY or not AI_API_KEY.strip():
        return None, ErrorCode.CONFIG, None
    config = _build_config(payload, timeout)

    response = await asyncio.wait_for(
        _client().aio.models.generate_content(
            model    = model,
            contents = payload.contents,
            config   = config,
        ),
        timeout = timeout,
    )

    text, err = _extract_answer(response)
    if err:
        return None, err, getattr(response, "usage_metadata", None)
    return text, None, getattr(response, "usage_metadata", None)


async def generate_answer(
    question: str,
    history: Iterable[dict[str, Any]] | None = None,
    *,
    user_id: str | None = None,
    request_id: str | None = None,
) -> AIResult:
    """오류 분류에 따라 재시도·폴백을 적용해 AI 응답을 생성한다.

    AI 호출 실패는 AIResult로 반환하고, 작업 취소는 호출자에게 전달한다.
    입력 검증·DB 저장·HTTP 오류 변환은 chat_main에서 처리한다.
    """
    request_id = request_id or uuid.uuid4().hex[:12]
    payload    = build_contents(question, history)

    candidates = [AI_MODEL]
    if AI_FALLBACK_MODEL and AI_FALLBACK_MODEL != AI_MODEL:
        candidates.append(AI_FALLBACK_MODEL)

    log_event(
        "ai_call_start",
        request_id    = request_id,
        model         = AI_MODEL,
        fallback      = AI_FALLBACK_MODEL,
        context_turns = payload.turns_used,
        q_len         = len(question),
    )

    started            = time.perf_counter()
    last_code          = ErrorCode.UNKNOWN
    last_model         = AI_MODEL
    fallback_attempted = False

    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def remaining() -> float:
        return AI_TOTAL_TIMEOUT_SECONDS - (time.perf_counter() - started)

    for model_index, model in enumerate(candidates):
        is_fallback = model_index > 0
        last_model  = model

        # 주 모델은 시도하되, 폴백을 수행할 시간이 부족하면 이전 실패를 유지한다.
        budget = min(AI_TIMEOUT_SECONDS, remaining())
        if is_fallback and budget <= MIN_FALLBACK_BUDGET_SECONDS:
            log_event("ai_fallback_skip", model=model, request_id=request_id)
            break

        if is_fallback:
            fallback_attempted = True
            log_event(
                "ai_fallback_start",
                request_id     = request_id,
                previous_model = candidates[0],
                model          = model,
                error_code     = last_code,
            )

        for attempt in range(AI_MAX_RETRIES + 1):
            try:
                answer, err_code, usage = await _call_once(model, payload, budget)

                if err_code is None:
                    log_event(
                        "ai_call_success",
                        request_id = request_id,
                        model      = model,
                        latency_ms = elapsed_ms(),
                        attempt    = attempt + 1,
                        fallback   = is_fallback,
                        a_len      = len(answer or ""),
                    )
                    # 외부 AI 모델 호출 성공: chat_main.py로 전달될 정상 결과 객체(status="success") 반환
                    return AIResult(
                        # 성공 상태 플래그 (chat_main.py에서 성공 여부 분기 기준이 됨)
                        status            = "success",
                        # 요청 추적용 식별자
                        request_id        = request_id,
                        # 응답 생성에 최종 사용된 모델명
                        model             = model,
                        # 호출 완료까지 소요된 시간 (ms)
                        latency_ms        = elapsed_ms(),
                        # 모델이 생성한 텍스트 답변
                        answer            = answer,
                        # 프롬프트에 소모된 토큰 수
                        prompt_tokens     = getattr(usage, "prompt_token_count", None),
                        # 응답 생성에 소모된 토큰 수
                        completion_tokens = getattr(usage, "candidates_token_count", None),
                        # 기본 모델 실패 후 대체(폴백) 모델을 사용했는지 여부
                        fallback_used     = is_fallback,
                    )

                last_code = err_code
                log_event(
                    "ai_call_fail",
                    request_id = request_id,
                    model      = model,
                    error_code = err_code,
                    attempt    = attempt + 1,
                )

            except Exception as exc:
                last_code = _classify(exc)
                log_event(
                    "ai_call_fail",
                    request_id = request_id,
                    model      = model,
                    error_code = last_code,
                    attempt    = attempt + 1,
                    exc        = exc,
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
    log_event(
        "ai_call_giveup",
        request_id = request_id,
        model      = last_model,
        error_code = last_code,
        latency_ms = elapsed_ms(),
        fallback   = fallback_attempted,
    )
    return AIResult(
        status        = status,
        request_id    = request_id,
        model         = last_model,
        latency_ms    = elapsed_ms(),
        error_code    = last_code,
        user_message  = USER_MESSAGES.get(last_code, USER_MESSAGES[ErrorCode.UNKNOWN]),
        fallback_used = fallback_attempted,
    )
