"""Gemini 네트워크 호출 없이 문맥·오류 분류·폴백을 검증한다."""
import asyncio
import os
import subprocess
import sys
from types            import SimpleNamespace
from unittest.mock    import AsyncMock, Mock

import httpx
import pytest
from google.genai     import errors, types

from app.core.errors  import APIError, ErrorCode
from app.schemas.chat import ChatRequest
from app.services     import AI_connect as ai, chat_main


@pytest.mark.parametrize("question", ["", " \n ", "가" * 5001], ids=["empty", "blank", "too-long"])
def test_validation_is_in_service(question):
    request = ChatRequest(room_id="room-a", room_name="Test room", question=question)
    with pytest.raises(APIError) as error:
        chat_main.validate_question(request)
    assert error.value.status_code == 422


def test_context_uses_recent_complete_turns_and_preserves_order(monkeypatch):
    monkeypatch.setattr(ai, "AI_CONTEXT_TURNS", 2)
    monkeypatch.setattr(ai, "MAX_CONTEXT_CHARS", 100)
    payload = ai.build_contents("next", [
        {"question": "old", "answer": "old answer"},
        {"question": "one", "answer": "answer one"},
        {"question": "failed", "answer": None},
        {"question": "two", "answer": "answer two"},
    ])
    assert payload.turns_used == 2
    assert [entry["role"] for entry in payload.contents] == ["user", "model", "user", "model", "user"]
    assert [entry["parts"][0]["text"] for entry in payload.contents] == ["one", "answer one", "two", "answer two", "next"]


@pytest.mark.parametrize("limit,turns,texts", [
    (8, 1, ["q", "a", "next"]),
    (3, 0, ["next"]),
])
def test_context_limit_discards_oldest_turn_without_truncating_question(monkeypatch, limit, turns, texts):
    monkeypatch.setattr(ai, "AI_CONTEXT_TURNS", 5)
    monkeypatch.setattr(ai, "MAX_CONTEXT_CHARS", limit)
    payload = ai.build_contents("next", [{"question": "old", "answer": "old"}, {"question": "q", "answer": "a"}])
    assert payload.turns_used == turns
    assert payload.truncated
    assert ai.CONTEXT_TRUNCATED_NOTICE in payload.system_instruction
    assert [entry["parts"][0]["text"] for entry in payload.contents] == texts


@pytest.mark.parametrize("exception,code", [
    (TimeoutError(), ErrorCode.TIMEOUT),
    (httpx.ReadTimeout("private"), ErrorCode.TIMEOUT),
    (httpx.ConnectError("private"), ErrorCode.CONNECTION),
    (errors.APIError(429, {}), ErrorCode.RATE_LIMIT),
    (errors.APIError(400, {}), ErrorCode.BAD_REQUEST),
    (errors.APIError(401, {}), ErrorCode.CONFIG),
    (errors.APIError(403, {}), ErrorCode.CONFIG),
    (errors.APIError(400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}), ErrorCode.CONFIG),
    (errors.APIError(400, {"details": [{"reason": "API_KEY_SERVICE_BLOCKED"}]}), ErrorCode.CONFIG),
    (errors.APIError(400, {"message": "API key not valid. Please pass a valid API key."}), ErrorCode.CONFIG),
    (errors.APIError(404, {}), ErrorCode.BAD_REQUEST),
    (errors.APIError(503, {}), ErrorCode.UPSTREAM),
    (RuntimeError("private"), ErrorCode.UNKNOWN),
])
def test_classifies_provider_errors(exception, code):
    assert ai._classify(exception) == code


@pytest.mark.parametrize("response,answer,code", [
    (SimpleNamespace(text=" answer "), "answer", None),
    (SimpleNamespace(text="", prompt_feedback=SimpleNamespace(block_reason="SAFETY")), "", ErrorCode.BLOCKED),
    (SimpleNamespace(text=None, candidates=[SimpleNamespace(finish_reason="SAFETY")]), "", ErrorCode.BLOCKED),
    (SimpleNamespace(text=" ", candidates=[]), "", ErrorCode.EMPTY_RESPONSE),
    (SimpleNamespace(text="partial", candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")]), "", ErrorCode.TOKEN_LIMIT),
    (SimpleNamespace(text=None, candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")]), "", ErrorCode.TOKEN_LIMIT),
    (SimpleNamespace(text="partial", candidates=[SimpleNamespace(finish_reason="SAFETY")]), "", ErrorCode.BLOCKED),
])
def test_extracts_answer_or_block_reason(response, answer, code):
    assert ai._extract_answer(response) == (answer, code)


@pytest.fixture
def ai_settings(monkeypatch):
    for name, value in {
        "AI_MODEL": "primary", "AI_FALLBACK_MODEL": "fallback", "AI_MAX_RETRIES": 0,
        "AI_TIMEOUT_SECONDS": 10, "AI_TOTAL_TIMEOUT_SECONDS": 24,
        "MIN_FALLBACK_BUDGET_SECONDS": 0.5,
    }.items():
        monkeypatch.setattr(ai, name, value)


@pytest.mark.anyio
async def test_primary_success_preserves_usage_metadata(ai_settings, monkeypatch):
    call = AsyncMock(return_value=("answer", None, SimpleNamespace(prompt_token_count=10, candidates_token_count=20)))
    monkeypatch.setattr(ai, "_call_once", call)
    result = await ai.generate_answer("question", request_id="request")
    assert (result.status, result.answer, result.model, result.request_id) == ("success", "answer", "primary", "request")
    assert (result.prompt_tokens, result.completion_tokens, result.fallback_used) == (10, 20, False)
    call.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("code,fallback", [
    (ErrorCode.BAD_REQUEST, True), (ErrorCode.TIMEOUT, True),
    (ErrorCode.UPSTREAM, True), (ErrorCode.EMPTY_RESPONSE, True),
    (ErrorCode.BLOCKED, False), (ErrorCode.UNKNOWN, True),
    (ErrorCode.CONFIG, False), (ErrorCode.TOKEN_LIMIT, False),
])
async def test_fallback_policy(ai_settings, monkeypatch, code, fallback):
    call = AsyncMock(side_effect=[(None, code, None), ("recovered", None, None)])
    monkeypatch.setattr(ai, "_call_once", call)
    result = await ai.generate_answer("question")
    assert result.fallback_used is fallback
    assert result.status == ("success" if fallback else "error")
    assert [entry.args[0] for entry in call.await_args_list] == (["primary", "fallback"] if fallback else ["primary"])


@pytest.mark.anyio
async def test_fallback_equal_to_primary_is_not_called_again(ai_settings, monkeypatch):
    monkeypatch.setattr(ai, "AI_FALLBACK_MODEL", "primary")
    call = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(ai, "_call_once", call)
    result = await ai.generate_answer("question")
    assert result.status == "timeout"
    assert not result.fallback_used
    call.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("code,status", [(ErrorCode.TIMEOUT, "timeout"), (ErrorCode.RATE_LIMIT, "error")])
async def test_fallback_failure_preserves_error_and_last_model(ai_settings, monkeypatch, code, status):
    call = AsyncMock(return_value=(None, code, None))
    monkeypatch.setattr(ai, "_call_once", call)
    result = await ai.generate_answer("question", request_id="request")
    assert (result.status, result.error_code, result.model, result.fallback_used) == (status, code, "fallback", True)
    assert result.request_id == "request"
    assert result.user_message == ai.USER_MESSAGES[code]
    assert [entry.args[0] for entry in call.await_args_list] == ["primary", "fallback"]


@pytest.mark.anyio
async def test_call_once_enforces_timeout(monkeypatch):
    cancelled = asyncio.Event()

    async def slow(**kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    monkeypatch.setattr(
        ai,
        "_client",
        lambda: SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=slow))),
    )
    with pytest.raises(TimeoutError):
        await ai._call_once("primary", ai.PromptPayload(), 0.01)
    assert cancelled.is_set()


@pytest.mark.anyio
async def test_call_once_passes_context_config_and_usage(monkeypatch):
    usage = SimpleNamespace(prompt_token_count=10, candidates_token_count=20)
    generate = AsyncMock(return_value=SimpleNamespace(text=" answer ", usage_metadata=usage))
    monkeypatch.setattr(
        ai,
        "_client",
        lambda: SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))),
    )
    payload = ai.build_contents("question", [{"question": "previous", "answer": "answer"}])
    result = await ai._call_once("primary", payload, 1.25)
    assert result == ("answer", None, usage)
    kwargs = generate.await_args.kwargs
    assert kwargs["model"] == "primary"
    assert kwargs["contents"] == payload.contents
    assert kwargs["config"].system_instruction == payload.system_instruction
    assert kwargs["config"].http_options.timeout == 1250


@pytest.mark.anyio
async def test_cancellation_propagates_without_retry(ai_settings, monkeypatch):
    call = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(ai, "_call_once", call)
    with pytest.raises(asyncio.CancelledError):
        await ai.generate_answer("question")
    call.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("key", [None, "", "   "], ids=["missing", "empty", "blank"])
async def test_missing_key_stops_before_sdk_without_fallback(ai_settings, monkeypatch, key):
    monkeypatch.setattr(ai, "AI_API_KEY", key)
    monkeypatch.setattr(ai, "AI_MAX_RETRIES", 2)
    client = Mock(side_effect=AssertionError("SDK must not be constructed without a key"))
    monkeypatch.setattr(ai, "_client", client)
    result = await ai.generate_answer("question")
    assert (result.status, result.error_code, result.fallback_used) == ("error", ErrorCode.CONFIG, False)
    client.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [
    errors.APIError(401, {}), errors.APIError(403, {}),
    errors.APIError(400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}),
])
async def test_invalid_key_stops_after_one_sdk_call(ai_settings, monkeypatch, failure):
    monkeypatch.setattr(ai, "AI_MAX_RETRIES", 2)
    generate = AsyncMock(side_effect=failure)
    monkeypatch.setattr(ai, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))))
    result = await ai.generate_answer("question")
    assert (result.status, result.error_code, result.fallback_used) == ("error", ErrorCode.CONFIG, False)
    generate.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("answer", ["", "partial answer"])
async def test_max_tokens_discards_partial_response_without_retry(ai_settings, monkeypatch, answer):
    monkeypatch.setattr(ai, "AI_MAX_RETRIES", 2)
    response = types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(parts=[types.Part(text=answer)]), finish_reason=types.FinishReason.MAX_TOKENS,
    )])
    generate = AsyncMock(return_value=response)
    monkeypatch.setattr(ai, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))))
    result = await ai.generate_answer("question")
    assert (result.status, result.error_code, result.answer, result.fallback_used) == ("error", ErrorCode.TOKEN_LIMIT, None, False)
    generate.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("code,retries_primary", [
    (ErrorCode.UPSTREAM, True), (ErrorCode.RATE_LIMIT, True), (ErrorCode.CONNECTION, True),
    (ErrorCode.EMPTY_RESPONSE, False), (ErrorCode.BAD_REQUEST, False),
], ids=["upstream", "rate-limit", "connection", "empty", "bad-request"])
async def test_transient_failures_retry_primary_before_falling_back(
    ai_settings, monkeypatch, code, retries_primary,
):
    """제공사 5xx는 일시적이므로 폴백보다 주 모델 재시도를 먼저 쓴다."""
    monkeypatch.setattr(ai, "AI_MAX_RETRIES", 1)
    monkeypatch.setattr(ai.asyncio, "sleep", AsyncMock())
    call = AsyncMock(side_effect=[(None, code, None), ("recovered", None, None)])
    monkeypatch.setattr(ai, "_call_once", call)

    result = await ai.generate_answer("question")

    assert (result.status, result.answer) == ("success", "recovered")
    assert [entry.args[0] for entry in call.await_args_list] == [
        "primary", "primary" if retries_primary else "fallback",
    ]
    assert result.fallback_used is not retries_primary


@pytest.mark.anyio
async def test_primary_retry_exhausted_still_falls_back(ai_settings, monkeypatch):
    """주 모델 재시도가 모두 실패하면 폴백 모델까지 이어서 시도한다."""
    monkeypatch.setattr(ai, "AI_MAX_RETRIES", 1)
    monkeypatch.setattr(ai.asyncio, "sleep", AsyncMock())
    call = AsyncMock(side_effect=[
        (None, ErrorCode.UPSTREAM, None),
        (None, ErrorCode.UPSTREAM, None),
        ("recovered", None, None),
    ])
    monkeypatch.setattr(ai, "_call_once", call)

    result = await ai.generate_answer("question")

    assert (result.status, result.answer, result.fallback_used) == ("success", "recovered", True)
    assert [entry.args[0] for entry in call.await_args_list] == ["primary", "primary", "fallback"]


@pytest.mark.anyio
async def test_call_deadline_never_drops_below_provider_minimum(ai_settings, monkeypatch):
    """남은 예산이 적어도 제공사 하한 미만으로 호출하지 않는다.

    하한보다 짧은 deadline은 400 INVALID_ARGUMENT로 거부되므로,
    예산을 깎아 호출하면 폴백이 확정적으로 실패한다.
    """
    monkeypatch.setattr(ai, "AI_MAX_RETRIES", 1)
    monkeypatch.setattr(ai, "AI_TOTAL_TIMEOUT_SECONDS", 0.2)  # 사실상 예산 없음
    monkeypatch.setattr(ai.asyncio, "sleep", AsyncMock())
    call = AsyncMock(return_value=(None, ErrorCode.UPSTREAM, None))
    monkeypatch.setattr(ai, "_call_once", call)

    await ai.generate_answer("question")

    deadlines = [entry.args[2] for entry in call.await_args_list]
    assert deadlines, "주 모델은 예산과 무관하게 한 번은 호출한다"
    from app.core.config import AI_MIN_DEADLINE_SECONDS
    assert all(value >= AI_MIN_DEADLINE_SECONDS for value in deadlines), deadlines


@pytest.mark.anyio
async def test_skipped_fallback_is_not_reported_as_the_failed_model(ai_settings, monkeypatch):
    """폴백을 건너뛰면 실제로 호출한 주 모델이 기록되어야 한다."""
    monkeypatch.setattr(ai, "MIN_FALLBACK_BUDGET_SECONDS", float("inf"))
    call = AsyncMock(return_value=(None, ErrorCode.UPSTREAM, None))
    monkeypatch.setattr(ai, "_call_once", call)

    result = await ai.generate_answer("question")

    assert [entry.args[0] for entry in call.await_args_list] == ["primary"]
    assert result.model == "primary"
    assert result.fallback_used is False


def test_zero_context_turns_disables_history(monkeypatch):
    """AI_CONTEXT_TURNS=0 은 문맥을 쓰지 않겠다는 뜻이다. turns[-0:] 는 전체를 남긴다."""
    history = [{"question": f"q{index}", "answer": f"a{index}"} for index in range(10)]
    monkeypatch.setattr(ai, "AI_CONTEXT_TURNS", 0)
    payload = ai.build_contents("new", history)
    assert payload.turns_used == 0
    assert [entry["parts"][0]["text"] for entry in payload.contents] == ["new"]


@pytest.mark.parametrize("raw", ["", "   ", "not-a-number"], ids=["empty", "blank", "invalid"])
def test_blank_numeric_setting_falls_back_to_default(monkeypatch, raw):
    """`.env`가 빈 값으로 기본값을 쓰도록 안내하므로 숫자 항목도 죽지 않아야 한다."""
    from app.core.config import _num
    monkeypatch.setenv("SOME_NUMERIC_SETTING", raw)
    assert _num("SOME_NUMERIC_SETTING", "7", int) == 7
    assert _num("SOME_NUMERIC_SETTING", "1.5", float) == 1.5


def test_configured_timeout_is_raised_to_provider_minimum():
    """하한보다 낮게 설정해도 400을 부르지 않도록 끌어올린다."""
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "from app.core.config import AI_TIMEOUT_SECONDS, AI_MIN_DEADLINE_SECONDS; "
         "assert AI_TIMEOUT_SECONDS == AI_MIN_DEADLINE_SECONDS, AI_TIMEOUT_SECONDS"],
        env={**os.environ, "AI_TIMEOUT_SECONDS": "3"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
