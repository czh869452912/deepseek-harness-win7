from dsh.core.agent import AgentPlugin
from dsh.core.session import SessionPlugin
import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.tools import ToolsPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.abort import AbortController
from dsh.subagent.in_process import InProcessProvider
from dsh.subagent.descriptor import snapshot_descriptor, fold_descriptor
from dsh.subagent.runtime import SubagentRuntime, SubagentError, settle_run
from dsh.subagent.in_process import SpawnInProcess


class Model:
    provider, model = "fixture", "fixture"

    def __init__(self):
        self.requests = []

    async def chat_completion_stream(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        yield {"choices": [{"delta": {"content": "actual child answer", "role": "assistant"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


async def setup():
    ctx, model = Context(), Model()
    ctx.set_service("llm", model)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(AgentLoopPlugin)
    handle = await ctx.get("agent_loop").create("parent")
    return ctx, model, handle


@pytest.mark.asyncio
@pytest.mark.parametrize("fork", [False, True])
async def test_actual_child_execution_owns_session_context_and_result(fork):
    ctx, model, parent = await setup()
    run = None
    try:
        parent.agent.followup("parent secret")
        await parent.agent.when_idle()
        provider = InProcessProvider("fork" if fork else "spawn", fork)
        request = {"parent": parent.agent, "prompt": [{"type": "text", "text": "child task"}],
                   "signal": AbortController().signal, "maxDepth": 1,
                   "descriptor": snapshot_descriptor({"mode": "one-shot", "provider": provider.name, "label": "test"})}
        run = await ctx.get("agents").with_initiator_async(parent.agent, provider.start(request))
        assert ctx.get("agents").get(run.id) is run.localAgent
        result = await asyncio.wait_for(run.result, 3)
        assert result == {"output": [{"type": "text", "text": "actual child answer"}], "stopReason": "completed"}
        assert ("parent secret" in str(model.requests[-1]["messages"])) is fork
        assert run.localAgent.session.header.parentSession == parent.agent.id
        assert run.localAgent.session.header.delegationDepth == 1
        assert fold_descriptor(run.localAgent.session.events)["provider"] == provider.name
        await run.dispose()
        assert ctx.get("agents").get(run.id) is None
    finally:
        if run is not None:
            await run.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_prepublication_abort_and_depth_limit_never_publish_child():
    ctx, model, parent = await setup()
    try:
        provider, controller = InProcessProvider("spawn"), AbortController()
        request = {"parent": parent.agent, "prompt": [], "signal": controller.signal,
                   "descriptor": snapshot_descriptor({"mode": "one-shot", "provider": "spawn"})}
        controller.abort("stop")
        with pytest.raises(RuntimeError, match="before child publication"):
            await provider.start(request)
        request["signal"] = AbortController().signal
        request["maxDepth"] = 0
        with pytest.raises(ValueError, match="exceeds"):
            await provider.start(request)
        assert ctx.get("agents").list() == [parent.agent]
        assert not model.requests
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_structured_request_does_not_accept_plain_text_as_success():
    ctx, model, parent = await setup()
    run = None
    try:
        request = {"parent": parent.agent, "prompt": [{"type": "text", "text": "structured task"}],
                   "signal": AbortController().signal, "outputSchema": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
                   "descriptor": snapshot_descriptor({"mode": "one-shot", "provider": "spawn"})}
        run = await InProcessProvider("spawn").start(request)
        result = await asyncio.wait_for(run.result, 3)
        assert result["stopReason"] == "error" and "structured" not in result
        assert ctx.get("tools").get("structured_output") is None
        assert "structured_output" in str(model.requests[-1]["tools"])
    finally:
        if run is not None:
            await run.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_registry_owns_registration_but_published_run_survives_provider_unload():
    ctx, model, parent = await setup()
    run = None
    try:
        await ctx.plugin(SubagentRuntime)
        provider = await ctx.plugin(SpawnInProcess)
        runtime = ctx.get("subagents")
        edges = []
        def broken(info):
            raise RuntimeError("bad observer")
        ctx.on("subagent/start", broken)
        ctx.on("subagent/start", lambda info: edges.append(("start", info["id"])))
        ctx.on("subagent/end", lambda info: edges.append(("end", info["stopReason"])))
        run = await runtime.start("spawn", {"parent": parent.agent, "prompt": [{"type": "text", "text": "task"}], "signal": AbortController().signal})
        await provider.dispose()
        assert runtime.list() == []
        with pytest.raises(SubagentError) as failure:
            await runtime.start("spawn", {})
        assert failure.value.code == "NO_PROVIDER"
        assert (await settle_run(run))["status"] == "completed"
        assert edges == [("start", run.id), ("end", "completed")]
    finally:
        if run is not None:
            await run.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_structured_capture_commits_only_authoritative_result_and_stops_later_tools():
    ctx, model, parent = await setup()
    run = None
    async def structured(messages, tools=None, **kwargs):
        yield {"choices": [{"delta": {"role": "assistant", "tool_calls": [{"index": 0, "id": "capture",
            "type": "function", "function": {"name": "structured_output", "arguments": '{"value":"accepted"}'}}]}, "finish_reason": "tool_calls"}]}
    model.chat_completion_stream = structured
    try:
        await ctx.plugin(SubagentRuntime)
        await ctx.plugin(SpawnInProcess)
        run = await ctx.get("subagents").start("spawn", {"parent": parent.agent, "prompt": [{"type": "text", "text": "task"}],
            "signal": AbortController().signal, "outputSchema": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False}})
        result = await asyncio.wait_for(run.result, 3)
        assert result["stopReason"] == "completed" and result["structured"] == {"value": "accepted"}
        assert ctx.get("tools").get("structured_output") is None
    finally:
        if run is not None:
            await run.dispose()
        await parent.dispose()
        await ctx.fiber.dispose()
