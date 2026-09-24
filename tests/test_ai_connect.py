"""Gemini 네트워크 호출 없이 문맥·오류 분류·폴백을 검증한다."""
import asyncio
from types            import SimpleNamespace
from unittest.mock    import AsyncMock

import httpx
import pytest
from google.genai     import errors

from app.core.errors  import APIError, ErrorCode
from app.schemas.chat import ChatRequest
from app.services     import AI_connect as ai, chat_main


@pytest.mark.parametrize("question", ["", " \n ", "가" * 5001], ids=["empty", "blank", "too-long"])
def test_validation_is_in_service(question):
    request = ChatRequest(question=question)
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
    (errors.APIError(403, {}), ErrorCode.BAD_REQUEST),
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
