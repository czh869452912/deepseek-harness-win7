"""Pinned workflow contracts, native Ralph execution and real child isolation."""
from dsh.core.agent import AgentPlugin
from dsh.core.session import SessionPlugin

import asyncio
import copy
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolExecutionInput, ToolsPlugin
from dsh.core.cancellation import subscribe_abort
from dsh.subagent.in_process import SpawnInProcess
from dsh.subagent.runtime import SubagentRuntime
from dsh.workflow.ralph import RALPH_META, RALPH_SCRIPT, execute_ralph, read_result, render_result
from dsh.workflow.text import json_text, utf16_length
from dsh.workflow.tool_ralph import ToolRalphPlugin
from dsh.workflow.tool_workflow import ToolWorkflowPlugin
from dsh.workflow.workflow_service import WorkflowEngine, WorkflowError, validate_meta

CONTINUE = dict(status="continue", summary="Implemented the first slice.", evidence=["Focused tests pass."],
                nextSteps=["Implement the second slice."], blocker="")
COMPLETE = dict(status="complete", summary="The objective is complete.", evidence=["All required gates pass."], nextSteps=[], blocker="")
BLOCKED = dict(status="blocked", summary="No local work can progress.", evidence=["The service is unavailable."],
               nextSteps=["Retry after recovery."], blocker="The service is down.")
META = dict(name="probe", description="Observe real orchestration.")


class Records:
    def __init__(self, failure=None):
        self.events, self.failure = [], failure

    def append(self, name, data):
        if self.failure == name:
            raise RuntimeError("recording unavailable")
        self.events.append(dict(type=name, data=copy.deepcopy(data)))


class Child:
    def __init__(self, number, result=None, pending=False):
        self.id, self.disposed = "child-" + str(number), 0
        self.result = asyncio.get_event_loop().create_future()
        if not pending:
            if isinstance(result, Exception):
                self.result.set_exception(result)
            else:
                self.result.set_result(result or dict(stopReason="completed", output=[dict(type="text", text="child answer")]))

    async def dispose(self):
        self.disposed += 1
        if not self.result.done():
            self.result.set_result(dict(stopReason="aborted", output=[]))


class Provider:
    name, inheritsParentContext = "spawn", False
    capabilities = dict(agentOptions=True, outputSchema=True, depthLimit=True, toolFilter=True, persona=True)

    def __init__(self, reports=(), pending=False):
        self.reports, self.pending = list(reports), pending
        self.requests, self.children = [], []
        self.entered, self.release = asyncio.Event(), None
        self.failure = None

    async def start(self, request):
        self.requests.append(request)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        index = len(self.children)
        if self.reports:
            report = self.reports[index]
            result = (report if isinstance(report, Exception) else
                      dict(stopReason="error", output=[]) if report is None else
                      dict(stopReason="completed", output=[], structured=copy.deepcopy(report)))
        else:
            result = None
        child = Child(index + 1, result, self.pending)
        self.children.append(child)
        return child


async def setup(reports=(), engine_config=None, ralph_config=None, provider=None):
    ctx = Context()
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(SubagentRuntime)
    provider = provider or Provider(reports)
    ctx.get("subagents").registerProvider(provider)
    engine_fiber = await ctx.plugin(WorkflowEngine, engine_config or {})
    ralph_fiber = await ctx.plugin(ToolRalphPlugin, ralph_config or {})
    workflow_fiber = await ctx.plugin(ToolWorkflowPlugin)
    parent = SimpleNamespace(id="parent", ctx=ctx, session=Records(), options={})
    return ctx, provider, parent, engine_fiber, ralph_fiber, workflow_fiber


async def execute(ctx, parent, args, name="ralph", signal=None, nested=None):
    return await ctx.get("tools").execute(ToolExecutionInput("call", name, args,
        agent=parent, signal=signal or AbortController().signal, parent=nested))


def observe(ctx):
    events = []
    for name in ("start", "phase", "log", "agent-start", "agent-end", "end"):
        def record(*args, name=name):
            events.append((name, copy.deepcopy(args)))
        ctx.on("workflow/" + name, record)
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("reports,status", [([COMPLETE], "complete"), ([BLOCKED], "blocked"),
    ([CONTINUE, COMPLETE], "complete"), ([CONTINUE, CONTINUE], "budget-limited")])
async def test_ralph_executes_real_rounds_and_validates_terminal_state(reports, status):
    ctx, provider, parent, _, _, _ = await setup(reports)
    events = observe(ctx)
    try:
        result = await execute(ctx, parent, dict(objective="  Finish migration  ", maxRounds=len(reports)))
        assert not result.is_error, result.content
        assert result.value["agentsStarted"] == len(reports)
        assert result.value["result"]["status"] == status
        assert result.value["result"]["roundsStarted"] == len(reports)
        assert len(provider.requests) == len(reports)
        assert all(child.disposed == 1 for child in provider.children)
        assert provider.requests[0]["parent"] is parent
        assert "Immutable objective:\nFinish migration" in provider.requests[0]["prompt"][0]["text"]
        assert "outputSchema" in provider.requests[0]
        if len(reports) > 1:
            assert json_text(CONTINUE) in provider.requests[1]["prompt"][0]["text"]
        assert [name for name, _ in events].count("agent-start") == len(reports)
        assert [name for name, _ in events].count("agent-end") == len(reports)
        assert events[-1][0] == "end" and "value" not in events[-1][1][1]
        assert all(event[1][0]["id"] == result.value["runId"] for event in events)
        assert not ctx.get("workflowEngine")._active_runs
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("reports", [[None], [CONTINUE, None]])
async def test_failed_child_is_tool_error_with_last_handoff(reports):
    ctx, provider, parent, _, _, _ = await setup(reports)
    try:
        result = await execute(ctx, parent, dict(objective="Finish", maxRounds=2))
        assert result.is_error
        text = str(result.content)
        assert "failed before producing a structured report" in text
        assert ("Last successful handoff" in text) is (len(reports) == 2)
        assert ("No previous handoff" in text) is (len(reports) == 1)
        assert all(child.disposed == 1 for child in provider.children)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("report,fragment", [
    (dict(COMPLETE, summary=" "), "summary must be"),
    (dict(CONTINUE, nextSteps=[]), "continuing Ralph report"),
    (dict(COMPLETE, evidence=[]), "complete Ralph report"),
    (dict(BLOCKED, blocker=""), "blocked Ralph report"),
    (dict(COMPLETE, evidence=[" bad"]), "only non-empty normalized"),
    (dict(COMPLETE, status="unknown"), "status is invalid"),
])
async def test_malformed_child_report_never_becomes_success(report, fragment):
    ctx, _, parent, _, _, _ = await setup([report])
    try:
        result = await execute(ctx, parent, dict(objective="Finish"))
        assert result.is_error and fragment in str(result.content)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("args,fragment", [
    (dict(objective=" \ufeff "), "non-empty"), (dict(objective="Finish", maxRounds=0), "positive safe-integer"),
    (dict(objective="Finish", maxRounds=1.5), "positive safe-integer"),
    (dict(objective="Finish", maxRounds=257), "deployment ceiling"),
])
async def test_invalid_ralph_arguments_start_no_child(args, fragment):
    ctx, provider, parent, _, _, _ = await setup([COMPLETE])
    try:
        result = await execute(ctx, parent, args)
        assert result.is_error and fragment.replace("safe-integer", "safe integer") in str(result.content)
        assert not provider.requests
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["freshness", "schema", "missing", "parent"])
async def test_ralph_requires_fresh_structured_provider_and_parent(invalid):
    provider = Provider([COMPLETE])
    if invalid == "freshness":
        provider.inheritsParentContext = True
    if invalid == "schema":
        provider.capabilities = dict(provider.capabilities, outputSchema=False)
    ctx, provider, parent, _, _, _ = await setup(provider=provider,
        ralph_config=dict(subagentProvider="missing") if invalid == "missing" else None)
    try:
        result = await execute(ctx, None if invalid == "parent" else parent, dict(objective="Finish"))
        assert result.is_error
        assert {"freshness": "requires a fresh provider", "schema": "does not support structured output",
                "missing": "not registered", "parent": "requires a calling agent"}[invalid] in str(result.content)
        assert not provider.requests
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ralph_bounds_handoff_and_entire_render_in_utf16_units():
    report = dict(COMPLETE, summary="\U0001f600" * 40)
    cap = utf16_length(json_text(report)) - 1
    ctx, _, parent, _, _, _ = await setup([report], ralph_config=dict(maxHandoffChars=cap))
    try:
        result = await execute(ctx, parent, dict(objective="Finish"))
        assert result.is_error and "exceeds maxHandoffChars" in str(result.content)
    finally:
        await ctx.fiber.dispose()
    for limit in (1, 5, 14, 50, 80):
        rendered = render_result(dict(status="complete", roundsStarted=1, report=report), limit)
        assert utf16_length(rendered) <= limit


@pytest.mark.asyncio
async def test_generic_js_fails_before_run_publication_and_durable_recording():
    ctx, provider, parent, _, _, _ = await setup([COMPLETE])
    events = observe(ctx)
    try:
        result = await execute(ctx, parent, dict(script="return await agent('test');", meta=META), "workflow")
        assert result.is_error and "JavaScript workflow execution is not available" in str(result.content)
        with pytest.raises(WorkflowError) as failure:
            ctx.get("workflowEngine").start(dict(script="return 1", meta=META, parent=parent))
        assert failure.value.code == "SCRIPT_RUNTIME_UNAVAILABLE"
        assert not events and not provider.requests and not parent.session.events
        assert ctx.get("tools").get("run_workflow") is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_workflow_records_real_top_level_run_in_correct_order(nested):
    ctx, provider, parent, _, _, _ = await setup([COMPLETE])
    try:
        result = await execute(ctx, parent, dict(script=RALPH_SCRIPT, meta=RALPH_META,
            args=dict(objective="Finish", maxRounds=1, maxHandoffChars=16384)), "workflow", nested=object() if nested else None)
        assert not result.is_error, result.content
        assert result.value["result"]["status"] == "complete"
        assert all(child.disposed == 1 for child in provider.children)
        events = parent.session.events
        if nested:
            assert not events
        else:
            assert [event["type"] for event in events] == ["tool-workflow/run-start", "tool-workflow/agent-start",
                "tool-workflow/agent-end", "tool-workflow/run-end"]
            assert events[1]["data"]["childId"] == provider.children[0].id
            assert events[2]["data"]["outcome"] == "completed"
            assert events[-1]["data"]["stopReason"] == "completed"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tool-workflow/run-start", "tool-workflow/agent-start", "tool-workflow/agent-end", "tool-workflow/run-end"])
async def test_recording_failure_is_contained(failure):
    ctx, _, parent, _, _, _ = await setup([COMPLETE])
    parent.session = Records(failure)
    try:
        result = await execute(ctx, parent, dict(script=RALPH_SCRIPT, meta=RALPH_META,
            args=dict(objective="Finish", maxRounds=1, maxHandoffChars=16384)), "workflow")
        assert not result.is_error, result.content
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_pipeline_has_no_stage_barrier_and_drops_only_failed_items():
    ctx, _, parent, _, _, _ = await setup()
    blocked, fast_second = asyncio.Event(), asyncio.Event()
    async def program(run):
        async def first(prev, item, index):
            if item == "slow":
                await blocked.wait()
            if item == "bad":
                raise ValueError("ordinary stage error")
            return item + "1"
        async def second(prev, item, index):
            if item == "fast":
                fast_second.set()
            return prev + "2"
        return await run.pipeline(["slow", "fast", "bad"], first, second)
    ctx.get("workflowEngine").register_native_program("native-pipeline", program)
    run = ctx.get("workflowEngine").start(dict(script="native-pipeline", meta=META, parent=parent))
    try:
        await asyncio.wait_for(fast_second.wait(), 1)
        assert not blocked.is_set() and not run.result.done()
        blocked.set()
        assert (await run.result)["value"] == ["slow12", "fast12", None]
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_parallel_fifo_agent_slots_and_llm_overrides():
    ctx, provider, parent, _, _, _ = await setup(engine_config=dict(maxConcurrentAgents=1))
    events = observe(ctx)
    async def program(run):
        run.phase("work")
        return await run.parallel([lambda: run.agent("one", dict(provider="llm-target")),
                                   lambda: run.agent("two", dict(model="model-target"))])
    ctx.get("workflowEngine").register_native_program("native-parallel", program)
    run = ctx.get("workflowEngine").start(dict(script="native-parallel", meta=META, parent=parent))
    try:
        result = await run.result
        assert result["value"] == ["child answer", "child answer"] and result["agentsStarted"] == 2
        assert [request["prompt"][0]["text"] for request in provider.requests] == ["one", "two"]
        assert [request["agentOptions"] for request in provider.requests] == [dict(provider="llm-target"), dict(model="model-target")]
        assert [name for name, _ in events] == ["start", "phase", "agent-start", "agent-end", "agent-start", "agent-end", "end"]
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["agent-cap", "item-cap", "option", "schema", "start", "result", "json"])
async def test_fatal_errors_propagate_through_parallel(problem):
    ctx, provider, parent, _, _, _ = await setup(engine_config=dict(maxTotalAgents=1, maxItemsPerCall=1))
    if problem == "start":
        provider.failure = ValueError("backend start failed")
    if problem == "result":
        provider.reports = [ValueError("broken result")]
    async def program(run):
        if problem == "item-cap":
            return await run.parallel([lambda: 1, lambda: 2])
        if problem == "json":
            return float("nan")
        async def thunk():
            if problem == "agent-cap":
                await run.agent("first")
            return await run.agent("second", dict(effort="high") if problem == "option" else
                dict(schema=dict(type="object", pattern="bad")) if problem == "schema" else {})
        return await run.parallel([thunk])
    ctx.get("workflowEngine").register_native_program("native-errors", program)
    run = ctx.get("workflowEngine").start(dict(script="native-errors", meta=META, parent=parent))
    try:
        result = await run.result
        assert result["stopReason"] == "error" and result["value"] is None
        assert {"agent-cap": "total agent cap", "item-cap": "per-call cap", "option": "not supported",
            "schema": "supported subset", "start": "could not start", "result": "child agent run failed", "json": "not plain JSON"}[problem] in result["error"]
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancel_pairs_children_counts_queued_calls_and_first_reason_wins():
    provider = Provider(pending=True)
    ctx, provider, parent, _, _, _ = await setup(provider=provider, engine_config=dict(maxConcurrentAgents=1, disposeGraceMs=20))
    events = observe(ctx)
    async def program(run):
        return await run.parallel([lambda: run.agent("active"), lambda: run.agent("queued")])
    ctx.get("workflowEngine").register_native_program("native-cancel", program)
    run = ctx.get("workflowEngine").start(dict(script="native-cancel", meta=META, parent=parent))
    try:
        await provider.entered.wait()
        while not any(name == "agent-start" for name, _ in events):
            await asyncio.sleep(0)
        run.cancel("first reason")
        run.cancel("second reason")
        result = await asyncio.wait_for(asyncio.shield(run.result), 1)
        await asyncio.gather(run.dispose(), run.dispose())
        assert result["stopReason"] == "cancelled" and "first reason" in result["error"]
        assert result["agentsStarted"] == 2 and len(provider.requests) == 1
        starts = [args[1]["seq"] for name, args in events if name == "agent-start"]
        ends = [args[1]["seq"] for name, args in events if name == "agent-end"]
        assert starts == ends == [1]
        assert events[-1][0] == "end"
        assert provider.children[0].disposed == 1
        for callback, args in ((run.phase, ["late"]), (run.log, ["late"]), (run.parallel, [[]]), (run.pipeline, [[], lambda *_: None])):
            with pytest.raises(WorkflowError) as error:
                callback(*args)
            assert error.value.code == "CANCELLED"
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancel_reaps_late_provider_publication_without_member_events():
    provider = Provider()
    provider.release = asyncio.Event()
    ctx, provider, parent, _, _, _ = await setup(provider=provider, engine_config=dict(disposeGraceMs=10))
    events = observe(ctx)
    async def program(run):
        return await run.agent("late publication")
    ctx.get("workflowEngine").register_native_program("native-late", program)
    run = ctx.get("workflowEngine").start(dict(script="native-late", meta=META, parent=parent))
    try:
        await provider.entered.wait()
        await run.dispose()
        assert (await run.result)["stopReason"] == "cancelled"
        provider.release.set()
        for _ in range(100):
            if provider.children and provider.children[0].disposed:
                break
            await asyncio.sleep(0)
        assert provider.children[0].disposed == 1
        assert not [name for name, _ in events if name.startswith("agent-")]
    finally:
        provider.release.set()
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_run_survives_engine_unload_and_registration_is_caller_owned():
    ctx, provider, parent, engine_fiber, ralph_fiber, _ = await setup([COMPLETE])
    engine = ctx.get("workflowEngine")
    run = engine.start(dict(script=RALPH_SCRIPT, meta=RALPH_META, parent=parent,
        args=dict(objective="Finish", maxRounds=1, maxHandoffChars=16384)))
    try:
        await engine_fiber.dispose()
        assert ctx.get("workflowEngine") is None
        assert (await run.result)["value"]["status"] == "complete"
        assert len(provider.children) == 1
        await ralph_fiber.dispose()
        assert RALPH_SCRIPT not in engine._native_programs
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_preaborted_start_executes_no_program_and_observer_failure_is_contained():
    ctx, provider, parent, _, _, _ = await setup([COMPLETE])
    events = observe(ctx)
    def broken(*_):
        raise RuntimeError("observer failed")
    async def broken_async(*_):
        raise RuntimeError("async observer failed")
    ctx.on("workflow/start", broken)
    ctx.on("workflow/end", broken_async)
    controller = AbortController()
    controller.abort("early")
    run = ctx.get("workflowEngine").start(dict(script=RALPH_SCRIPT, meta=RALPH_META,
        args=dict(objective="Finish", maxRounds=1, maxHandoffChars=16384), parent=parent, signal=controller.signal))
    try:
        assert (await run.result)["stopReason"] == "cancelled"
        assert not provider.requests
        assert [name for name, _ in events] == ["start", "end"]
        await asyncio.sleep(0)
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


def test_meta_lists_all_violations_and_copies_data():
    with pytest.raises(WorkflowError) as error:
        validate_meta(dict(name="", description=3, unknown=1, phases=[dict(title="", model=2, extra=1), False]))
    assert error.value.code == "META_INVALID"
    for field in ("meta.name", "meta.description", "meta.unknown", "phases[0].title", "phases[0].model", "phases[0].extra", "phases[1]"):
        assert field in error.value.message
    value = dict(META, phases=[dict(title="phase", model="")])
    result = validate_meta(value)
    value["phases"][0]["title"] = "changed"
    assert result["phases"][0]["title"] == "phase"


@pytest.mark.parametrize("value", [dict(status="budget-limited", roundsStarted=1, report=CONTINUE),
    dict(status="round-failed", roundsStarted=2, lastReport=None),
    dict(status="complete", roundsStarted=True, report=COMPLETE),
    dict(status="complete", roundsStarted=1, report=dict(COMPLETE, extra=1)),
    dict(status="complete", roundsStarted=1, report=COMPLETE, extra=1)])
def test_defensive_terminal_decoder_rejects_untrusted_engine_results(value):
    with pytest.raises(ValueError):
        read_result(value, 2, 16384)


@pytest.mark.asyncio
async def test_actual_agent_loop_ralph_children_have_no_parent_or_prior_child_seed():
    class Model:
        provider, model = "fixture", "fixture"
        def __init__(self):
            self.requests = []
        async def chat_completion_stream(self, messages, tools=None, **kwargs):
            self.requests.append(copy.deepcopy(messages))
            if len(self.requests) == 1:
                yield dict(choices=[dict(delta=dict(role="assistant", content="parent-only secret response"), finish_reason="stop")])
            else:
                report = CONTINUE if len(self.requests) == 2 else COMPLETE
                yield dict(choices=[dict(delta=dict(role="assistant", tool_calls=[dict(index=0, id="capture", type="function",
                    function=dict(name="structured_output", arguments=json_text(report)))]), finish_reason="tool_calls")])
    ctx, model = Context(), Model()
    ctx.set_service("llm", model)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(AgentLoopPlugin)
    await ctx.plugin(SubagentRuntime)
    await ctx.plugin(SpawnInProcess)
    await ctx.plugin(WorkflowEngine)
    await ctx.plugin(ToolRalphPlugin)
    parent = await ctx.get("agent_loop").create("actual-parent")
    events = observe(ctx)
    try:
        parent.agent.followup("parent-only secret request")
        await parent.agent.when_idle()
        result = await asyncio.wait_for(execute(ctx, parent.agent, dict(objective="Finish concrete work", maxRounds=2)), 5)
        assert not result.is_error, result.content
        assert result.value["agentsStarted"] == 2 and result.value["result"]["status"] == "complete"
        assert len(model.requests) == 3
        assert "parent-only secret" not in str(model.requests[1]) + str(model.requests[2])
        assert "Implemented the first slice." not in str(model.requests[1])
        assert "Implemented the first slice." in str(model.requests[2])
        ids = [args[1]["childId"] for name, args in events if name == "agent-start"]
        assert len(set(ids)) == 2 and parent.agent.id not in ids
        assert ctx.get("agents").list() == [parent.agent]
        assert ctx.get("tools").get("structured_output") is None
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_dispose_claims_before_reentrant_child_abort_and_disposal():
    ctx, provider, parent, _, _, _ = await setup(provider=Provider(pending=True), engine_config=dict(disposeGraceMs=20))
    reentered = []
    async def program(run):
        return await run.agent("pending child")
    ctx.get("workflowEngine").register_native_program("native-reentrant", program)
    run = ctx.get("workflowEngine").start(dict(script="native-reentrant", meta=META, parent=parent))
    try:
        await provider.entered.wait()
        while not run._live:
            await asyncio.sleep(0)
        provider.requests[0]["signal"].add_listener("abort", lambda *_: reentered.append(run.dispose()))
        original = provider.children[0].dispose
        async def disposing():
            reentered.append(run.dispose())
            await original()
        provider.children[0].dispose = disposing
        await run.dispose()
        await asyncio.gather(*reentered)
        assert len(reentered) == 2 and provider.children[0].disposed == 1
        assert (await run.result)["stopReason"] == "cancelled"
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_force_cancel_of_program_parked_outside_hooks_is_bounded():
    ctx, _, parent, _, _, _ = await setup(engine_config=dict(disposeGraceMs=10))
    entered = asyncio.Event()
    async def program(run):
        entered.set()
        await asyncio.get_event_loop().create_future()
    ctx.get("workflowEngine").register_native_program("native-park", program)
    run = ctx.get("workflowEngine").start(dict(script="native-park", meta=META, parent=parent))
    try:
        await entered.wait()
        run.cancel("external cancellation")
        result = await asyncio.wait_for(asyncio.shield(run.result), 0.5)
        assert result["stopReason"] == "cancelled" and result["agentsStarted"] == 0
        assert "external cancellation" in result["error"]
        await run.dispose()
        assert run._driver.done()
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["caller", "wrapper"])
async def test_tool_composed_signal_cancels_ralph_and_detaches_listeners(which):
    ctx, provider, parent, _, _, _ = await setup(provider=Provider(pending=True), engine_config=dict(disposeGraceMs=10))
    caller, wrapper = AbortController(), AbortController()
    received = []
    async def around(execution, next_fn):
        execution.signal = wrapper.signal
        return await next_fn()
    ctx.on("tools/execute", around)
    task = asyncio.create_task(execute(ctx, parent, dict(objective="Finish"), signal=caller.signal))
    try:
        await provider.entered.wait()
        while not provider.children:
            await asyncio.sleep(0)
        provider.requests[0]["signal"].add_listener("abort", lambda reason: received.append(reason))
        (caller if which == "caller" else wrapper).abort("stop")
        result = await asyncio.wait_for(task, 1)
        assert result.is_error and "cancelled" in str(result.content)
        assert received == ["workflow signal aborted"]
        assert provider.children[0].disposed == 1
        assert not caller.signal._listeners and not wrapper.signal._listeners
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_legacy_event_subscription_detaches_and_fires_once():
    event, calls = asyncio.Event(), []
    detach = subscribe_abort(event, lambda reason: calls.append(reason))
    event.set()
    await asyncio.sleep(0)
    assert calls == [None]
    detach()
    second = asyncio.Event()
    detach = subscribe_abort(second, lambda _: calls.append("late"))
    detach()
    second.set()
    await asyncio.sleep(0)
    assert calls == [None]


@pytest.mark.asyncio
async def test_fused_tool_signal_retains_first_reason_and_detaches_at_dispatch_end():
    from dsh.core.tools import _FusedSignal
    caller, wrapper = AbortController(), AbortController()
    fused = _FusedSignal(caller.signal, wrapper.signal)
    calls = []
    fused.add_listener("abort", lambda reason: calls.append(reason))
    wrapper.abort("wrapper first")
    caller.abort("caller later")
    assert calls == ["wrapper first"] and fused.reason == "wrapper first"
    assert not caller.signal._listeners and not wrapper.signal._listeners
    caller, wrapper = AbortController(), AbortController()
    fused = _FusedSignal(caller.signal, wrapper.signal)
    fused.dispose()
    assert not caller.signal._listeners and not wrapper.signal._listeners
    caller.abort("detached")
    assert not fused.aborted
    caller, wrapper = AbortController(), AbortController()
    caller.abort("caller")
    wrapper.abort("wrapper")
    assert _FusedSignal(caller.signal, wrapper.signal).reason == "wrapper"


@pytest.mark.asyncio
async def test_completed_result_wins_cleanup_reentrant_cancellation():
    ctx, provider, parent, _, _, _ = await setup([COMPLETE])
    run = ctx.get("workflowEngine").start(dict(script=RALPH_SCRIPT, meta=RALPH_META, parent=parent,
        args=dict(objective="Finish", maxRounds=1, maxHandoffChars=16384)))
    try:
        result = await run.result
        run.cancel("too late")
        await run.dispose()
        assert (await run.result) == result and result["stopReason"] == "completed"
        assert provider.children[0].disposed == 1
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_workflow_real_web_profile_records_survive_cold_restart(tmp_path):
    from canonical_web_fixture import web_context, close_web_context
    from dsh.presets.mount import service_for_agent
    directory = tmp_path / "home"
    ctx = await web_context(directory)
    try:
        await ctx.get("sessionController").create(dict(sessionId="workflow-web", cwd=str(tmp_path), agentPreset="standard"))
        parent = ctx.get("agents").get("workflow-web")
        provider = Provider()
        provider.name = "workflow-record-probe"
        ctx.get("subagents").registerProvider(provider)
        engine = service_for_agent(ctx, parent, "workflowEngine")
        engine.config["provider"] = provider.name
        script = 'phase("actual records");return {answer:await agent("recorded child")}'
        assert ctx.get('jsRuntime') is not None
        result = await execute(ctx, parent, dict(script=script, meta=META), "workflow")
        assert not result.is_error, result.content
        assert result.value["result"] == dict(answer="child answer")
        assert await parent.session.flush()
        expected = [event for event in parent.session.events if event["type"].startswith("tool-workflow/")]
        assert [event["type"] for event in expected] == ["tool-workflow/run-start", "tool-workflow/agent-start",
            "tool-workflow/agent-end", "tool-workflow/run-end"]
    finally:
        await close_web_context(ctx)
    ctx = await web_context(directory)
    try:
        restored = await ctx.get("sessionController").inspect("workflow-web")
        actual = [event for event in restored["events"] if event["type"].startswith("tool-workflow/")]
        assert actual == expected
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_forced_finish_uses_host_start_count_and_preserves_empty_reason():
    ctx, provider, parent, _, _, _ = await setup(provider=Provider(pending=True), engine_config=dict(maxConcurrentAgents=1, disposeGraceMs=10))
    async def program(run):
        run.agent("started")
        run.agent("queued")
        await asyncio.get_event_loop().create_future()
    engine = ctx.get("workflowEngine")
    engine.register_native_program("native-forced", program)
    run = engine.start(dict(script="native-forced", meta=META, parent=parent))
    try:
        await provider.entered.wait()
        while not run._live:
            await asyncio.sleep(0)
        run.cancel("")
        result = await asyncio.wait_for(asyncio.shield(run.result), 1)
        assert result["stopReason"] == "cancelled" and result["agentsStarted"] == 1
        assert run.started == 2 and result["error"] == "workflow run cancelled: "
        assert provider.requests[0]["signal"].reason == ""
    finally:
        await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_explicit_null_agent_options_are_invalid_and_route_uses_js_trim():
    ctx, provider, parent, _, _, _ = await setup()
    async def program(run):
        return await run.agent("prompt", None)
    engine = ctx.get("workflowEngine")
    engine.register_native_program("native-null", program)
    run = engine.start(dict(script="native-null", meta=META, parent=parent))
    try:
        result = await run.result
        assert result["stopReason"] == "error" and "options must be an object" in result["error"]
        assert not provider.requests
        with pytest.raises(WorkflowError) as failure:
            engine.start(dict(script="native-null", meta=META, parent=parent, subagentProvider="\ufeffspawn"))
        assert failure.value.code == "INVALID_ARGUMENT"
        unusual = Provider()
        unusual.name = "\u0085spawn\u0085"
        ctx.get("subagents").registerProvider(unusual)
        second = engine.start(dict(script="native-null", meta=META, parent=parent, subagentProvider=unusual.name))
        await second.result
        await second.dispose()
    finally:
        await run.dispose()
        await ctx.fiber.dispose()
