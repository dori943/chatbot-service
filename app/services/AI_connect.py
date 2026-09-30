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


# ==============================================================================
# [설정 빌더: _build_config]
# Google GenAI SDK 규격의 GenerateContentConfig 설정 객체를 동적으로 조립
# 1) 기본 설정(base): 시스템 지침, 온도(temperature), 최대 토큰, HTTP 타임아웃(ms)
# 2) 부가 설정(extra): 함수 호출 비활성화(AFC disable), 추론 레벨(thinking_config)
# 3) 버전 호환성 방어: SDK 버전에 따라 extra 파라미터를 지원하지 않으면 기본 base로만 자동 폴백
# ==============================================================================
# Gemini API 호출 시 전달할 세부 하이퍼파라미터 및 네트워크 설정 객체 생성 함수
def _build_config(
    # 조립된 대화 내용 및 시스템 지침이 담긴 페이로드
    payload: PromptPayload,
    # 해당 호출에 할당된 제한 시간(초 단위 float)
    timeout: float,
) -> Any:
    """GenerateContentConfig 를 만든다.

    SDK 버전에 따라 지원하지 않는 옵션이 있을 수 있으므로,
    부가 옵션은 실패해도 기본 설정으로 넘어가도록 방어한다.
    """
    # 필수적인 기본 생성 파라미터 딕셔너리 구성
    base = dict(
        # AI 모델의 역할 및 행동 지침 (과거 대화 생략 안내문 포함)
        system_instruction = payload.system_instruction,
        # 답변의 무작위성/창의성 조절 (낮을수록 일관되고 결정론적인 답변 생성)
        temperature        = AI_TEMPERATURE,
        # 모델이 생성할 수 있는 최대 출력 토큰 수 제한 (비용 및 응답 길이 통제)
        max_output_tokens  = AI_MAX_TOKENS,
        # HTTP 네트워크 옵션: SDK는 밀리초(ms) 단위를 요구하므로 초(s) * 1000 변환 적용
        http_options       = types.HttpOptions(timeout=int(timeout * 1000)),  # ms
    )
    # SDK 버전에 따라 선택적으로 지원되는 부가 옵션 딕셔너리
    extra: dict[str, Any] = {}

    # 자동 함수 호출(AFC, Automatic Function Calling) 기능 비활성화 처리
    # (일반 텍스트 챗봇이므로 도구 호출을 차단하여 불필요한 네트워크 왕복 지연 및 경고 방지)
    try:
        # 구글 SDK 최신 규격의 함수 호출 비활성화 옵션 주입
        extra["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            # AFC 완전 끄기
            disable = True
        )
    # 구버전 SDK이거나 해당 설정을 지원하지 않는 경우 조용히 무시(Pass)
    except Exception:  # noqa: BLE001 - 구버전 SDK
        pass

    # 모델의 내부 추론(Thinking) 단계 조절 설정 (지원 모델에 한함)
    # (추론 단계를 낮추어 토큰 소모를 줄이고 사용자 응답 속도를 극대화)
    if AI_THINKING_LEVEL:
        try:
            # 설정에 지정된 추론 레벨 주입
            extra["thinking_config"] = types.ThinkingConfig(
                # 추론 강도 레벨 지정
                thinking_level = AI_THINKING_LEVEL
            )
        # 미지원 버전 또는 모델인 경우 로그 기록 후 예외 격리
        except Exception:  # noqa: BLE001
            log_event("ai_config_option_ignored")

    # 기본 설정(base)과 부가 설정(extra)을 언패킹(**)하여 최종 설정 객체 생성 시도
    try:
        return types.GenerateContentConfig(**base, **extra)
    # 설치된 SDK 버전이 낮아 extra 옵션 파라미터를 인식하지 못해 TypeError가 발생한 경우
    except TypeError:
        # 설정 다운그레이드 이벤트 로깅
        log_event("ai_config_fallback")
        # 안전한 기본 설정(base)만으로 객체를 생성하여 반환 (하위 호환성 보장)
        return types.GenerateContentConfig(**base)


# ==============================================================================
# [단일 호출기: _call_once]
# 특정 모델(주 모델 또는 폴백 모델)에 대해 1회 네트워크 요청을 수행하는 핵심 통신 함수
# 1) API 키 부재 사전 차단: 네트워크 호출 전 즉시 CONFIG 에러 반환
# 2) 2중 타임아웃 방어막: SDK 내부 HttpOptions + 파이썬 asyncio.wait_for의 이중 보호
# 3) 비동기 호출: _client().aio(AsyncIO)를 통해 서버 이벤트 루프를 블로킹하지 않음
# 4) 결과 및 토큰 사용량 파싱: _extract_answer()로 텍스트/에러 분리 및 usage_metadata 반환
# ==============================================================================
# 지정된 모델에 프롬프트를 전송하고 1회 생성 결과를 받아오는 비동기 함수
async def _call_once(
    # 호출 대상 AI 모델 식별자 (예: gemini-2.0-flash 등)
    model: str,
    # build_contents에서 조립된 프롬프트 페이로드
    payload: PromptPayload,
    # 이번 시도에 할당된 가용 시간(초)
    timeout: float,
) -> tuple[str | None, str | None, Any]:
    # -------------------------------------------------------------------------
    # 독스트링(Docstring, Documentation String)이란? 고급 주석이다.
    #   - 파이썬에서 함수/클래스 바로 아래에 붙이는 '공식 제품 설명서' 문법 (큰따옴표 3개: """ ... """)
    #   - 일반 주석(#)과의 3가지 결정적 차이점 (고급 주석인 이유):
    #     1) 에디터 연동: VS Code 등에서 함수 이름에 마우스를 올렸을 때(Hover) 팝업 툴팁으로 표시됨
    #     2) 런타임 메모리 보존: 파이썬 실행 중에도 지워지지 않고 함수명.__doc__ 변수에 영구 보관됨
    #     3) 문서 자동화: FastAPI Swagger UI(/docs)나 문서 빌더(Sphinx)가 이를 읽어 공식 API 문서로 자동 변환
    # -------------------------------------------------------------------------
    """모델을 한 번 호출한다. 반환: (answer, error_code, usage_metadata).

    asyncio.wait_for 로 타임아웃을 직접 강제한다.
    SDK 내부 타임아웃 동작에 의존하지 않기 위함이다.
    """
    # API 키 환경변수가 비어있거나 누락된 경우 네트워크 요청 없이 설정 에러 즉시 반환
    if not AI_API_KEY or not AI_API_KEY.strip():
        return None, ErrorCode.CONFIG, None
    # 이번 호출의 타임아웃을 반영한 GenerateContentConfig 설정 조립
    config = _build_config(payload, timeout)

    # 파이썬 이벤트 루프 레벨에서 엄격한 타임아웃을 강제하는 비동기 대기
    # (SDK 내부의 HTTP 소켓 타임아웃 오작동이나 무한 행(Hang) 현상 원천 차단)
    response = await asyncio.wait_for(
        # GenAI 클라이언트의 aio(AsyncIO) 비동기 엔드포인트를 통해 모델 생성 API 호출
        _client().aio.models.generate_content(
            # 호출할 모델명
            model    = model,
            # 포맷팅된 대화 메시지 목록
            contents = payload.contents,
            # 조립된 설정 객체
            config   = config,
        ),
        # asyncio.wait_for의 제한 시간 (초과 시 TimeoutError 발생)
        timeout = timeout,
    )

    # API 응답 객체에서 실제 텍스트 및 안전 검열/토큰 초과 등의 사유 분리 추출
    text, err = _extract_answer(response)
    # 검열(BLOCKED), 토큰한도(TOKEN_LIMIT) 등 내부 에러 코드가 감지된 경우 에러 코드 반환
    if err:
        return None, err, getattr(response, "usage_metadata", None)
    # 정상 생성 완료 시 추출된 텍스트와 토큰 사용량(usage_metadata) 반환
    return text, None, getattr(response, "usage_metadata", None)


# ==============================================================================
# [최상위 오케스트레이터: generate_answer]
# 서비스 계층(chat_main.py)이 호출하는 AI 서비스의 메인 엔트리포인트 함수
# 1) 후보군 등록: 주 모델(AI_MODEL) 및 보조 폴백 모델(AI_FALLBACK_MODEL)을 후보 리스트로 관리
# 2) 시간 예산(Budget): 전체 제한시간(AI_TOTAL_TIMEOUT_SECONDS) 내에서 남은 가용 시간을 실시간 계산
# 3) 2중 중첩 루프: [외부] 모델 교체 루프(candidates) ➔ [내부] 동일 모델 재시도 루프(AI_MAX_RETRIES)
# 4) 지수 백오프(Backoff): 재시도 간격(0.5s * attempt)을 점진적으로 늘려 외부 서버 부하 경감
# 5) 지능형 탈출: 재시도 가능 에러(RETRY_SAME_MODEL) 및 폴백 가능 에러(FALLBACK_TRIGGERS)를 엄격히 감별
# 6) 무장애 방어: 어떤 실패가 발생해도 서버를 죽이지 않고 AIResult(status='timeout'|'error') 반환
# ==============================================================================
# 외부 LLM 모델에 질문을 전송하고 답변 또는 장애 대체 객체(AIResult)를 반환하는 비동기 메인 함수
async def generate_answer(
    # 사용자 질문 원문
    question: str,
    # 자연스러운 대화 맥락 유지를 위해 시간순으로 정렬된 이전 대화 목록
    history: Iterable[dict[str, Any]] | None = None,
    # 파이썬 키워드 전용 인자(Keyword-only argument) 강제 구분자 (* 이후는 이름=값 형태로만 전달 가능)
    *,
    # 요청을 보낸 사용자 고유 식별자
    user_id: str | None = None,
    # 분산 환경 및 로그 추적용 요청 식별자
    request_id: str | None = None,
) -> AIResult:
    # -------------------------------------------------------------------------
    # ■ 독스트링(Docstring): 개발자 및 IDE를 위한 공식 함수 사용 설명서
    # -------------------------------------------------------------------------
    """오류 분류에 따라 재시도·폴백을 적용해 AI 응답을 생성한다.

    AI 호출 실패는 AIResult로 반환하고, 작업 취소는 호출자에게 전달한다.
    입력 검증·DB 저장·HTTP 오류 변환은 chat_main에서 처리한다.
    """
    # 전달받은 request_id가 없으면 12자리 난수 고유 식별자를 신규 발급
    request_id = request_id or uuid.uuid4().hex[:12]
    # 5단계 파이프라인을 거쳐 Gemini API 규격의 프롬프트 페이로드 조립
    payload    = build_contents(question, history)

    # 1순위로 호출할 기본 주 모델(AI_MODEL)을 후보 리스트에 등록
    candidates = [AI_MODEL]
    # 보조 모델(AI_FALLBACK_MODEL)이 설정되어 있고 주 모델과 다를 경우 2순위 후보로 등록
    if AI_FALLBACK_MODEL and AI_FALLBACK_MODEL != AI_MODEL:
        candidates.append(AI_FALLBACK_MODEL)

    # AI 호출 시작 이벤트 로깅 (요청 ID, 모델명, 문맥 턴 수, 질문 길이 등)
    log_event(
        "ai_call_start",
        request_id    = request_id,
        model         = AI_MODEL,
        fallback      = AI_FALLBACK_MODEL,
        context_turns = payload.turns_used,
        q_len         = len(question),
    )

    # 고정밀 성능 측정 타이머 시작 (총 소요 시간 및 레이턴시 측정 기준점)
    started            = time.perf_counter()
    # 마지막으로 발생한 에러 코드를 추적하기 위한 변수 초기화
    last_code          = ErrorCode.UNKNOWN
    # 마지막으로 시도한 모델명을 기록하기 위한 변수 초기화
    last_model         = AI_MODEL
    # 보조(폴백) 모델 시도 여부 플래그
    fallback_attempted = False

    # 현재 시점까지 경과된 총 시간을 밀리초(ms)로 반환하는 내부 클로저 함수
    def elapsed_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    # 전체 허용 시간(AI_TOTAL_TIMEOUT_SECONDS) 중 아직 사용 가능한 남은 시간(초) 계산
    def remaining() -> float:
        return AI_TOTAL_TIMEOUT_SECONDS - (time.perf_counter() - started)

    # [외부 루프: 모델 교체 파이프라인] 주 모델부터 시작하여 실패 시 폴백 모델 순으로 순회
    for model_index, model in enumerate(candidates):
        # 인덱스가 0보다 크면 대체(폴백) 모델 실행 상태로 판정
        is_fallback = model_index > 0
        # 현재 시도 중인 모델명 갱신
        last_model  = model

        # 이번 1회 호출에 부여할 제한 시간(Budget): 단일 제한시간과 전체 잔여시간 중 작은 값 선택
        budget = min(AI_TIMEOUT_SECONDS, remaining())
        # 폴백 모델 차례인데 남은 시간이 최소 가용시간(예: 3초) 이하이면 무리하게 시도하지 않고 즉시 포기
        if is_fallback and budget <= MIN_FALLBACK_BUDGET_SECONDS:
            log_event("ai_fallback_skip", model=model, request_id=request_id)
            break

        # 폴백 모델 시도 플래그 활성화 및 폴백 전환 감사 로그 기록
        if is_fallback:
            fallback_attempted = True
            log_event(
                "ai_fallback_start",
                request_id     = request_id,
                previous_model = candidates[0],
                model          = model,
                error_code     = last_code,
            )

        # [내부 루프: 동일 모델 재시도 파이프라인] 최대 재시도 횟수(AI_MAX_RETRIES)만큼 호출 반복
        for attempt in range(AI_MAX_RETRIES + 1):
            try:
                # 단일 모델 1회 호출 수행 (타임아웃은 계산된 budget 적용)
                answer, err_code, usage = await _call_once(model, payload, budget)

                # 에러 코드가 없으면 모델 통신 성공
                if err_code is None:
                    # 호출 성공 메트릭 및 감사 로그 기록
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

                # 텍스트 추출 중 감지된 내부 에러(검열, 토큰 초과 등) 코드 갱신
                last_code = err_code
                # 호출 실패 이벤트 로깅
                log_event(
                    "ai_call_fail",
                    request_id = request_id,
                    model      = model,
                    error_code = err_code,
                    attempt    = attempt + 1,
                )

            # 네트워크 에러, 타임아웃, API 예외 등 발생 시 예외 처리
            except Exception as exc:
                # 발생한 파이썬 예외를 서비스 표준 에러 코드(ErrorCode)로 분류 변환
                last_code = _classify(exc)
                # 예외 상세 정보와 함께 호출 실패 로그 기록
                log_event(
                    "ai_call_fail",
                    request_id = request_id,
                    model      = model,
                    error_code = last_code,
                    attempt    = attempt + 1,
                    exc        = exc,
                )

            # 동일 모델로 재시도할 수 있는 조건인지 3중 검증
            # 1) 일시적 장애(503, 429, 네트워크 등)인지 여부 (401 키오류나 400 등은 재시도 무의미)
            # 2) 아직 최대 재시도 횟수(AI_MAX_RETRIES)가 남아있는지 여부
            # 3) 전체 남은 시간이 최소 1초 이상 남아있는지 여부
            can_retry = (
                last_code in RETRY_SAME_MODEL
                and attempt < AI_MAX_RETRIES
                and remaining() > 1.0
            )
            # 재시도 조건을 만족하지 못하면 내부 루프 즉시 탈출
            if not can_retry:
                break
            # 지수 백오프(Exponential Backoff): 재시도 횟수에 비례해 점진적으로 대기시간을 늘려 서버 회복 유도
            await asyncio.sleep(min(0.5 * (attempt + 1), max(0.0, remaining() - 0.5)))

        # 발생한 에러가 다른 모델로 바꾼다고 해결될 성질이 아닌 경우(예: 유해성 차단 등) 폴백 루프 즉시 중단
        if last_code not in FALLBACK_TRIGGERS:
            break

    # 타임아웃 에러인 경우 'timeout', 그 외의 에러는 'error'로 최종 결과 상태 결정
    status = "timeout" if last_code == ErrorCode.TIMEOUT else "error"
    # 모든 모델 및 재시도 실패(포기) 이벤트 감사 로그 기록
    log_event(
        "ai_call_giveup",
        request_id = request_id,
        model      = last_model,
        error_code = last_code,
        latency_ms = elapsed_ms(),
        fallback   = fallback_attempted,
    )
    # 서버 예외 발생 없이 chat_main.py가 핸들링할 수 있는 장애 대체 객체(AIResult) 최종 반환
    return AIResult(
        # 실패 상태 문자열 ('timeout' 또는 'error')
        status        = status,
        # 요청 식별자
        request_id    = request_id,
        # 최종 시도된 모델명
        model         = last_model,
        # 총 소요 시간 (ms)
        latency_ms    = elapsed_ms(),
        # 발생한 표준 에러 코드
        error_code    = last_code,
        # 사용자에게 화면으로 보여줄 친절한 안내 메시지 맵핑
        user_message  = USER_MESSAGES.get(last_code, USER_MESSAGES[ErrorCode.UNKNOWN]),
        # 폴백 모델 시도 여부
        fallback_used = fallback_attempted,
    )
