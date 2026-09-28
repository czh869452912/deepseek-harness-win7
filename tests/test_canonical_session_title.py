import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.core.session import SessionPlugin
from dsh.session.canonical_title import SessionTitleService
from dsh.session.title_llm import FirstPromptTitlePlugin
from dsh.llm.llm_service import LlmRuntime, LlmError
from dsh.llm.agent_request import mark_agent_loop_request
from dsh.core.abort import AbortController


async def setup():
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    fiber = await ctx.plugin(SessionTitleService, config={"fallbackMaxWords": 5, "fallbackMaxBytes": 40, "maxTitleBytes": 80})
    session = ctx.get("sessions").create("title-test")
    return ctx, ctx.get("sessionTitle"), session, fiber


@pytest.mark.asyncio
async def test_logged_route_starts_first_prompt_generation_and_user_rename_wins():
    ctx, titles, session, _ = await setup()
    pending = asyncio.get_running_loop().create_future()
    requests = []
    async def generate(request):
        requests.append(request)
        await pending
        return {"title": "Late model title", "messageSeqs": [request["messages"][0]["seq"]]}
    titles.register({"id": "test", "automatic": "first-prompt", "generate": generate})
    try:
        assert titles.get(session) is None
        session.append_user_message("Build a tool")
        await asyncio.sleep(0)
        assert not requests and titles.get(session)["source"] == {"kind": "fallback"}
        session.append_request_header({"config": {"provider": "local", "model": "test"}})
        await asyncio.sleep(0)
        assert requests[0]["route"] == {"provider": "local", "model": "test"}
        titles.rename(session, "Pinned title")
        assert requests[0]["signal"].aborted
        pending.set_result(None)
        await asyncio.sleep(0)
        assert titles.get(session)["title"] == "Pinned title"
    finally:
        if not pending.done():
            pending.set_result(None)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_provider_disposal_waits_for_inflight_settlement_and_blocks_replacement():
    ctx, titles, session, _ = await setup()
    session.append_user_message("A prompt")
    entered, release = asyncio.Event(), asyncio.Event()
    async def generate(request):
        entered.set()
        await release.wait()
        return {"title": "stale", "messageSeqs": [request["messages"][0]["seq"]]}
    disposer = titles.register({"id": "test", "automatic": "first-prompt", "generate": generate})
    try:
        refresh = asyncio.create_task(titles.refresh(session))
        await entered.wait()
        closing = asyncio.ensure_future(disposer())
        await asyncio.sleep(0)
        assert not closing.done()
        with pytest.raises(ValueError, match="already registered"):
            titles.register({"id": "other", "automatic": "first-prompt", "generate": generate})
        release.set()
        await closing
        with pytest.raises(RuntimeError):
            await refresh
        assert titles.get(session)["source"] == {"kind": "fallback"}
    finally:
        release.set()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_first_prompt_provider_records_exact_auxiliary_request_and_timeout(timeout):
    ctx, titles, session, _ = await setup()
    await ctx.plugin(LlmRuntime)
    captured = []
    class Adapter:
        async def stream(self, request):
            captured.append(request)
            if timeout:
                await asyncio.Event().wait()
            yield {"type": "block-start", "index": 0, "blockType": "text"}
            yield {"type": "text-delta", "index": 0, "text": "A useful title"}
            yield {"type": "block-end", "index": 0, "block": {"type": "text", "text": "A useful title"}}
            yield {"type": "finish", "reason": {"kind": "stop"}}
    ctx.get("llm").register_adapter(["fixture"], Adapter())
    await ctx.plugin(FirstPromptTitlePlugin, config={"targetWords": 5, "targetCjkCharacters": 10,
        "maxInputBytes": 4096, "maxOutputTokens": 64, "timeoutMs": 30 if timeout else 1000,
        "provider": "fixture", "model": "title"})
    try:
        session.append_user_message("Build something")
        if timeout:
            with pytest.raises(LlmError) as error:
                await titles.refresh(session)
            assert error.value.code == "SESSION_TITLE_TIMEOUT"
        else:
            result = await titles.refresh(session)
            assert result["title"] == "A useful title"
            assert result["source"]["model"] == {"provider": "fixture", "model": "title"}
        record = next(event["data"] for event in session.events if event["type"] == "session/title-llm-request")
        assert record["messages"] == captured[0]["messages"]
        assert captured[0]["purpose"] == "session-title" and captured[0]["maxTokens"] == 64
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unchanged_route_requires_main_agent_marker_and_open_step():
    ctx, titles, session, _ = await setup()
    calls = []
    async def generate(request):
        calls.append(request)
        return {"title": "Generated", "messageSeqs": [request["messages"][-1]["seq"]]}
    titles.register({"id": "test", "automatic": "all-prompts", "generate": generate})
    try:
        session.append_request_header({"config": {"provider": "fixture", "model": "main"}})
        session.append_user_message("New prompt on unchanged route")
        session.append("turn/start", {"turn": 0})
        session.append("step/start", {"turn": 0, "step": 0})
        request = {"sessionId": session.id, "provider": "fixture", "model": "main"}
        async def next_fn():
            return "stream"
        assert await ctx.waterfall("llm/stream", request, next_fn) == "stream"
        await asyncio.sleep(0)
        assert not calls
        await ctx.waterfall("llm/stream", mark_agent_loop_request(dict(request, model="other")), next_fn)
        await asyncio.sleep(0)
        assert not calls
        await ctx.waterfall("llm/stream", mark_agent_loop_request(request), next_fn)
        await asyncio.sleep(0)
        assert len(calls) == 1 and titles.get(session)["title"] == "Generated"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_seqs", [[], [999], [0, 0]])
async def test_invalid_provider_result_does_not_replace_fallback(invalid_seqs):
    ctx, titles, session, _ = await setup()
    async def generate(request):
        return {"title": "Invalid", "messageSeqs": invalid_seqs}
    titles.register({"id": "test", "automatic": "first-prompt", "generate": generate})
    try:
        session.append_user_message("Original title")
        with pytest.raises(ValueError):
            await titles.refresh(session)
        assert titles.get(session)["title"] == "Original title"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_refresh_cancellation_and_unpin_without_provider():
    ctx, titles, session, _ = await setup()
    try:
        session.append_user_message("Original title")
        titles.rename(session, "Pinned")
        controller = AbortController()
        controller.abort()
        with pytest.raises(RuntimeError, match="aborted"):
            await titles.refresh(session, controller.signal)
        assert titles.get(session)["title"] == "Pinned"
        assert (await titles.refresh(session))["source"] == {"kind": "fallback"}
    finally:
        await ctx.fiber.dispose()
