import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.tools import (
    ToolExecutionInput,
    ToolExecutionResult,
    ToolNotFoundError,
    ToolsService,
    ToolsPlugin,
)
from dsh.fs.fs_local import FsError
from dsh.llm.error import HarnessError


def make_tools(config=None):
    ctx = Context()
    tools = ToolsService(ctx, config=config)
    ctx.set_service("tools", tools)
    return ctx, tools


def test_optional_system_prompt_uses_minimal_context_get_contract():
    class Prompt:
        def __init__(self):
            self.providers = []

        def tools(self, provider):
            self.providers.append(provider)

    class Carrier:
        def __init__(self, services=None):
            self.services = services or {}

        def has(self, name):
            return name in self.services

        def get(self, name):
            return self.services[name]

    ToolsService(Carrier())
    prompt = Prompt()
    ToolsService(Carrier({"systemPrompt": prompt}))
    assert len(prompt.providers) == 1


def listen(ctx, event, callback):
    return ctx.events.on(event, callback, ctx=ctx)


@pytest.mark.asyncio
async def test_pipeline_uses_inner_thunks_and_passes_formal_run_context():
    ctx, tools = make_tools()
    order = []
    signal = asyncio.Event()
    agent = object()
    session = object()
    seen = {}

    async def pre(exec_ctx, next_fn):
        order.append("pre:before")
        decision = await next_fn()
        order.append("pre:after")
        return decision

    async def around(exec_ctx, next_fn):
        order.append("execute:before")
        result = await next_fn()
        order.append("execute:after")
        return result

    async def post(exec_ctx, result, next_fn):
        order.append("post:before")
        decision = await next_fn()
        order.append("post:after")
        return decision

    async def handler(value, exec):
        order.append("body")
        seen.update(
            call_id=exec.call_id,
            root_call_id=exec.root_call_id,
            agent=exec.agent,
            session=exec.session,
            signal=exec.signal,
            metadata=exec.metadata,
        )
        exec.defer_context({"kind": "deferred"})
        exec.conclude_turn()
        return value

    listen(ctx, "tools/pre-execute", pre)
    listen(ctx, "tools/execute", around)
    listen(ctx, "tools/post-execute", post)
    tools.register_legacy("echo", "echo", {}, handler)

    result = await tools.execute(
        ToolExecutionInput(
            "call-1", "echo", {"value": "ok"}, agent=agent, session=session,
            signal=signal, metadata={"turn": 3, "step": 2},
        )
    )

    assert order == [
        "pre:before", "pre:after", "execute:before", "body",
        "execute:after", "post:before", "post:after",
    ]
    assert seen == {
        "call_id": "call-1", "root_call_id": "call-1", "agent": agent,
        "session": session, "signal": signal, "metadata": {"turn": 3, "step": 2},
    }
    assert result.content == [{"type": "text", "text": "ok"}]
    assert result.additional_contexts == [{"kind": "deferred"}]
    assert result.concludes_turn is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, expected_name, expected_code",
    [
        (HarnessError("denied", "SANDBOX_DENIED"), "HarnessError", "SANDBOX_DENIED"),
        (FsError("stale", "FS_STALE_VERSION"), "FsError", "FS_STALE_VERSION"),
    ],
)
async def test_typed_errors_keep_their_name_and_code(error, expected_name, expected_code):
    _ctx, tools = make_tools()

    async def fail():
        raise error

    tools.register_legacy("fail", "fail", {}, fail)
    result = await tools.execute(ToolExecutionInput("c", "fail", {}, signal=asyncio.Event()))

    assert result.is_error is True
    assert result.error["message"] == error.message
    assert result.error["info"] == {"name": expected_name, "code": expected_code}
    assert result.error["code"] == expected_code


@pytest.mark.asyncio
async def test_pre_deny_skips_around_and_body_but_still_runs_post():
    ctx, tools = make_tools()
    phases = []

    async def body():
        phases.append("body")
        return "no"

    async def deny(_exec, _next):
        phases.append("pre")
        return {"kind": "deny", "reason": "not allowed"}

    async def around(_exec, next_fn):
        phases.append("around")
        return await next_fn()

    async def post(_exec, _result, next_fn):
        phases.append("post")
        return await next_fn()

    tools.register_legacy("blocked", "blocked", {}, body)
    listen(ctx, "tools/pre-execute", deny)
    listen(ctx, "tools/execute", around)
    listen(ctx, "tools/post-execute", post)

    prepared = await tools.prepare(ToolExecutionInput("c", "blocked", {}, signal=asyncio.Event()))
    assert prepared["kind"] == "post-result"
    result = await tools.finalize(prepared["exec"], prepared["result"])

    assert phases == ["pre", "post"]
    assert result.is_error is True
    assert result.content[0]["text"] == "Error: not allowed"


@pytest.mark.asyncio
async def test_scheduler_dispatch_preserves_prepare_short_circuit():
    ctx, tools = make_tools()
    body_calls = []

    tools.register_legacy("blocked", "blocked", {}, lambda: body_calls.append(True))

    async def deny(_exec, _next):
        return {"kind": "deny", "reason": "policy denied"}

    listen(ctx, "tools/pre-execute", deny)
    prepared = await tools.prepare(ToolExecutionInput("c", "blocked", {}, signal=asyncio.Event()))

    # The repository scheduler dispatches the prepared exec regardless of the
    # preparation tag, so the exec must retain the short-circuit decision.
    dispatched = await tools.dispatch(prepared["exec"])
    assert dispatched["kind"] == "post-result"
    assert dispatched["result"].error["message"] == "policy denied"
    assert body_calls == []


@pytest.mark.asyncio
async def test_around_short_circuit_and_post_block_are_normalized():
    ctx, tools = make_tools()
    body_calls = []

    async def body():
        body_calls.append(True)
        return "body"

    async def intercept(_exec, _next):
        return ToolExecutionResult.from_raw("intercepted")

    async def block(_exec, _result, _next):
        return {
            "kind": "block",
            "feedback": [{"type": "text", "text": "retry safely"}],
            "additionalContexts": [{"source": "policy"}],
        }

    tools.register_legacy("demo", "demo", {}, body)
    listen(ctx, "tools/execute", intercept)
    listen(ctx, "tools/post-execute", block)
    result = await tools.execute(ToolExecutionInput("c", "demo", {}, signal=asyncio.Event()))

    assert body_calls == []
    assert result.is_error is True
    assert result.error["message"] == "retry safely"
    assert result.additional_contexts == [{"source": "policy"}]


def test_registry_rejects_duplicates_and_disposer_only_removes_its_definition():
    _ctx, tools = make_tools()
    first = tools.register_legacy("echo", "one", {}, lambda: "one")
    with pytest.raises(ValueError, match="already registered"):
        tools.register_legacy("echo", "two", {}, lambda: "two")
    assert tools.get_tool("echo").description == "one"
    first()
    first()
    assert tools.get_tool("echo") is None


def test_schemas_are_detached_allowlisted_and_presentation_soft_validates():
    _ctx, tools = make_tools()
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    tools.register_legacy(
        {
            "name": "open",
            "description": "open",
            "parameters": parameters,
            "handler": lambda path: path,
            "timeoutMs": 50,
            "presentCall": lambda args: {"card": "generic", "title": args["path"]},
        }
    )

    schema = tools.schemas()[0]
    assert schema == {"name": "open", "description": "open", "parameters": parameters}
    assert "handler" not in schema and "timeoutMs" not in schema and "presentCall" not in schema
    schema["parameters"]["properties"]["path"]["type"] = "number"
    assert tools.schemas()[0]["parameters"]["properties"]["path"]["type"] == "string"

    tool = tools.get_tool("open")
    assert tool.present_call({"path": "a.txt"})["title"] == "a.txt"
    assert tool.present_call({}) is None


def test_config_mode_and_execution_classifier_follow_upstream_defaults():
    _ctx, tools = make_tools({"mode": "native", "maxParallelSubCalls": 4})
    tools.register_legacy(
        {
            "name": "read",
            "description": "read",
            "parameters": {
                "type": "object",
                "properties": {"safe": {"type": "boolean"}},
                "required": ["safe"],
            },
            "handler": lambda safe: safe,
            "isConcurrencySafe": lambda args: args["safe"] is True,
        }
    )
    assert tools.mode == "native"
    assert tools.max_parallel_sub_calls == 4
    assert tools.execution_mode(ToolExecutionInput("a", "read", {"safe": True}, signal=asyncio.Event())) == {"kind": "parallel"}
    assert tools.execution_mode(ToolExecutionInput("b", "read", {"safe": False}, signal=asyncio.Event())) == {"kind": "exclusive"}
    assert tools.execution_mode(ToolExecutionInput("c", "read", {}, signal=asyncio.Event())) == {"kind": "exclusive"}

    with pytest.raises(ValueError, match="mode"):
        ToolsService(Context(), config={"mode": "invalid"})
    with pytest.raises(ValueError, match="positive integer"):
        ToolsService(Context(), config={"maxParallelSubCalls": 0})


def test_tool_not_found_error_matches_harness_contract():
    error = ToolNotFoundError("ghost")
    assert isinstance(error, HarnessError)
    assert error.message == 'unknown tool "ghost"'
    assert error.code == "UNKNOWN_TOOL"


def test_execution_input_requires_caller_owned_signal():
    with pytest.raises(TypeError, match="signal"):
        ToolExecutionInput("c", "tool", {})


def canonical_tool(name, execute, finalize=None, safe=None):
    return {
        "name": name,
        "description": name,
        "parameters": {"type": "object", "properties": {}},
        "execute": execute,
        "output": {
            "schema": {"type": "string"},
            "render": lambda _args, value: [{"type": "text", "text": value}],
        },
        "finalizeContent": finalize,
        "isConcurrencySafe": safe,
    }


@pytest.mark.parametrize("mode", ["code", "both"])
def test_unavailable_code_modes_fail_at_config_boundary(mode):
    tools = ToolsService(Context(), config={"mode": mode})
    with pytest.raises(RuntimeError, match="requires a code runtime"):
        tools.schemas()


@pytest.mark.asyncio
async def test_pipeline_dispatches_from_agent_scope_target():
    root, tools = make_tools()
    scoped = root.extend()
    agent = SimpleNamespace(ctx=scoped, session=object())
    seen = []
    original = scoped.waterfall

    async def observed(event, data, *args, **kwargs):
        seen.append(event)
        return await original(event, data, *args, **kwargs)

    scoped.waterfall = observed
    tools.register(canonical_tool("scoped", lambda _args, _exec: "ok"))
    result = await tools.execute(ToolExecutionInput("c", "scoped", {}, agent=agent, signal=asyncio.Event()))

    assert result.is_error is False
    assert seen == ["tools/pre-execute", "tools/execute", "tools/post-execute"]


@pytest.mark.asyncio
async def test_cancellation_before_during_and_after_body_uses_stable_codes():
    _ctx, tools = make_tools()
    pre = asyncio.Event()
    pre.set()
    tools.register(canonical_tool("cancel", lambda _args, _exec: "ok"))
    before = await tools.execute(ToolExecutionInput("a", "cancel", {}, signal=pre))
    assert before.error["code"] == "ABORTED_BEFORE_DISPATCH"

    during = asyncio.Event()

    async def cancel_during(_args, exec):
        during.set()
        assert exec.signal.is_set()
        return "late success"

    tools.register(canonical_tool("during", cancel_during))
    after_body = await tools.execute(ToolExecutionInput("b", "during", {}, signal=during))
    assert after_body.error["code"] == "ABORTED"


@pytest.mark.asyncio
async def test_around_replacement_signal_is_fused_and_success_is_revalidated():
    ctx, tools = make_tools()
    caller = asyncio.Event()
    wrapper = asyncio.Event()
    observed = []

    async def body(_args, exec):
        observed.append(exec.signal)
        return "body"

    async def around(exec, next_fn):
        exec.signal = wrapper
        return await next_fn()

    tools.register(canonical_tool("wrapped", body))
    listen(ctx, "tools/execute", around)
    valid = await tools.execute(ToolExecutionInput("a", "wrapped", {}, signal=caller))
    assert valid.value == "body"
    assert observed[0] is not caller and observed[0] is not wrapper

    ctx.events._hooks["tools/execute"].clear()
    listen(ctx, "tools/execute", lambda _exec, _next: ToolExecutionResult([], value=42))
    invalid = await tools.execute(ToolExecutionInput("b", "wrapped", {}, signal=asyncio.Event()))
    assert invalid.error["code"] == "INVALID_TOOL_OUTPUT"


@pytest.mark.asyncio
async def test_around_signal_is_restored_when_body_throws():
    ctx, tools = make_tools()
    caller = asyncio.Event()
    wrapper = asyncio.Event()
    observed = []

    def explode(_args, _exec):
        raise RuntimeError("body broke")

    async def around(exec, next_fn):
        exec.signal = wrapper
        result = await next_fn()
        observed.append(exec.signal)
        return result

    tools.register(canonical_tool("signal-error", explode))
    listen(ctx, "tools/execute", around)
    result = await tools.execute(ToolExecutionInput(
        "c", "signal-error", {}, signal=caller))
    assert result.error == {"message": "body broke"}
    assert observed == [wrapper]


@pytest.mark.asyncio
async def test_arguments_are_deep_frozen_and_result_observer_failure_is_contained():
    ctx, tools = make_tools()
    mutations = []

    async def pre(exec, next_fn):
        with pytest.raises(TypeError):
            exec.arguments["nested"]["value"] = 2
        with pytest.raises(AttributeError):
            exec.name = "rewritten"
        mutations.append("frozen")
        return await next_fn()

    def bad_observer(_exec, _result):
        with pytest.raises(TypeError):
            _result.content.append({"type": "text", "text": "mutation"})
        raise RuntimeError("observer exploded")

    listen(ctx, "tools/pre-execute", pre)
    listen(ctx, "tools/result", bad_observer)
    tools.register(canonical_tool("frozen", lambda _args, _exec: "ok"))
    result = await tools.execute(ToolExecutionInput(
        "c", "frozen", {"nested": {"value": 1}}, signal=asyncio.Event()))

    assert result.is_error is False
    assert mutations == ["frozen"]
    with pytest.raises(TypeError):
        result.content[0]["text"] = "changed"


@pytest.mark.asyncio
async def test_value_replacement_preserves_context_conclusion_and_reprojects_meta():
    ctx, tools = make_tools()

    async def body(_args, exec):
        exec.defer_context({"source": "tool"})
        exec.conclude_turn()
        return "body"

    definition = canonical_tool("replace", body)
    definition["output"]["presentationMeta"] = lambda _args, value: {"value": value}
    tools.register(definition)
    listen(ctx, "tools/post-execute", lambda _exec, _result, _next: {
        "kind": "accept", "value": "replacement",
        "additionalContexts": [{"source": "policy"}],
    })
    result = await tools.execute(ToolExecutionInput("c", "replace", {}, signal=asyncio.Event()))

    assert result.value == "replacement"
    assert result.meta == {"value": "replacement"}
    assert result.additional_contexts == [{"source": "tool"}, {"source": "policy"}]
    assert result.concludes_turn is True


@pytest.mark.asyncio
async def test_post_value_replacement_projection_error_is_typed():
    ctx, tools = make_tools()
    definition = canonical_tool("post-render", lambda _args, _exec: "initial")
    definition["output"]["render"] = lambda _args, value: (
        (_ for _ in ()).throw(RuntimeError("replacement render broke"))
        if value == "replacement" else [{"type": "text", "text": value}])
    tools.register(definition)
    listen(ctx, "tools/post-execute", lambda _exec, _result, _next: {
        "kind": "accept", "value": "replacement"})

    result = await tools.execute(ToolExecutionInput(
        "c", "post-render", {}, signal=asyncio.Event()))
    assert result.error["code"] == "INVALID_TOOL_OUTPUT"
    assert "replacement render broke" in result.error["message"]


@pytest.mark.asyncio
async def test_finalizer_is_snapshotted_at_start_and_runs_once_on_error():
    ctx, tools = make_tools()
    calls = []

    def finalize(_exec, result):
        calls.append(result.is_error)
        return [{"type": "text", "text": "finalized"}]

    disposer = tools.register(canonical_tool("final", lambda _args, _exec: object(), finalize=finalize))

    async def remove(_exec, next_fn):
        disposer()
        return await next_fn()

    listen(ctx, "tools/pre-execute", remove)
    result = await tools.execute(ToolExecutionInput("c", "final", {}, signal=asyncio.Event()))
    assert result.content == [{"type": "text", "text": "finalized"}]
    assert calls == [True]


@pytest.mark.asyncio
async def test_post_cancellation_replaces_only_success_with_aborted():
    ctx, tools = make_tools()
    signal = asyncio.Event()
    tools.register(canonical_tool("post-cancel", lambda _args, _exec: "ok"))

    async def cancel(_exec, _result, next_fn):
        signal.set()
        return await next_fn()

    listen(ctx, "tools/post-execute", cancel)
    result = await tools.execute(ToolExecutionInput("c", "post-cancel", {}, signal=signal))
    assert result.error["code"] == "ABORTED"


@pytest.mark.asyncio
async def test_pre_aborted_skips_policy_and_around_cancel_before_body_is_pre_dispatch():
    ctx, tools = make_tools()
    phases = []
    tools.register(canonical_tool("cancel-stage", lambda _args, _exec: "body"))

    async def track_pre(_exec, next_fn):
        phases.append("pre")
        return await next_fn()

    listen(ctx, "tools/pre-execute", track_pre)
    signal = asyncio.Event()
    signal.set()
    result = await tools.execute(ToolExecutionInput("a", "cancel-stage", {}, signal=signal))
    assert result.error["code"] == "ABORTED_BEFORE_DISPATCH"
    assert phases == []

    caller = asyncio.Event()

    def cancel_without_next(_exec, _next):
        caller.set()
        return ToolExecutionResult([], value="short")

    listen(ctx, "tools/execute", cancel_without_next)
    result = await tools.execute(ToolExecutionInput("b", "cancel-stage", {}, signal=caller))
    assert result.error["code"] == "ABORTED_BEFORE_DISPATCH"


@pytest.mark.asyncio
async def test_dispatch_and_post_results_reject_attribute_rebinding():
    ctx, tools = make_tools()
    mutations = []
    tools.register(canonical_tool("immutable", lambda _args, _exec: "original"))

    async def around(_exec, next_fn):
        result = await next_fn()
        with pytest.raises(AttributeError):
            result.value = "around"
        mutations.append("around")
        return result

    async def post(_exec, result, next_fn):
        with pytest.raises(AttributeError):
            result.content = []
        mutations.append("post")
        return await next_fn()

    listen(ctx, "tools/execute", around)
    listen(ctx, "tools/post-execute", post)
    result = await tools.execute(ToolExecutionInput("c", "immutable", {}, signal=asyncio.Event()))
    with pytest.raises(AttributeError):
        result.meta = {"changed": True}
    assert mutations == ["around", "post"]
    assert result.value == "original"


@pytest.mark.asyncio
async def test_ask_calls_approval_service_and_allows_once():
    ctx, tools = make_tools()
    requests = []

    class Approval:
        async def request(self, request):
            requests.append(request)
            return "allowed-once"

    ctx.set_service("approval", Approval())
    agent = SimpleNamespace(ctx=ctx, session=object())
    tools.register(canonical_tool("approved", lambda _args, _exec: "ok"))
    listen(ctx, "tools/pre-execute", lambda _exec, _next: {"kind": "ask", "reason": "confirm"})
    result = await tools.execute(ToolExecutionInput(
        "c", "approved", {}, agent=agent, signal=asyncio.Event()))
    assert result.is_error is False
    assert requests[0]["toolName"] == "approved"
    assert requests[0]["callId"] == "c"


@pytest.mark.asyncio
async def test_supported_schema_enforces_one_of_additional_properties_and_projection_errors():
    _ctx, tools = make_tools()
    definition = canonical_tool("shape", lambda _args, _exec: {"ok": True, "extra": 1})
    definition["output"]["schema"] = {
        "oneOf": [
            {"type": "object", "properties": {"ok": {"type": "boolean"}},
             "required": ["ok"], "additionalProperties": False},
            {"type": "string"},
        ]
    }
    tools.register(definition)
    result = await tools.execute(ToolExecutionInput("c", "shape", {}, signal=asyncio.Event()))
    assert result.error["code"] == "INVALID_TOOL_OUTPUT"

    broken = canonical_tool("broken-render", lambda _args, _exec: "ok")
    broken["output"]["render"] = lambda _args, _value: (_ for _ in ()).throw(RuntimeError("render broke"))
    tools.register(broken)
    result = await tools.execute(ToolExecutionInput("d", "broken-render", {}, signal=asyncio.Event()))
    assert result.error["code"] == "INVALID_TOOL_OUTPUT"


@pytest.mark.asyncio
async def test_canonical_value_and_pre_failure_are_frozen_before_policy():
    ctx, tools = make_tools()
    tools.register({
        "name": "container", "description": "container", "parameters": {},
        "execute": lambda _args, _exec: {"nested": [1]},
        "output": {
            "schema": {"type": "object", "properties": {
                "nested": {"type": "array", "items": {"type": "integer"}}
            }, "required": ["nested"], "additionalProperties": False},
            "render": lambda _args, _value: [{"type": "text", "text": "ok"}],
        },
    })
    successful = await tools.execute(ToolExecutionInput(
        "a", "container", {}, signal=asyncio.Event()))
    with pytest.raises(TypeError):
        successful.value["nested"].append(2)

    async def deny(_exec, _next):
        return {"kind": "deny", "reason": "denied"}

    async def post(_exec, result, next_fn):
        with pytest.raises(AttributeError):
            result.is_error = False
        with pytest.raises(TypeError):
            result.content.append({"type": "text", "text": "forged"})
        return await next_fn()

    listen(ctx, "tools/pre-execute", deny)
    listen(ctx, "tools/post-execute", post)
    denied = await tools.execute(ToolExecutionInput(
        "b", "container", {}, signal=asyncio.Event()))
    assert denied.is_error is True
    assert denied.error["message"] == "denied"


@pytest.mark.asyncio
async def test_finalizer_gets_frozen_result_and_can_only_replace_content():
    _ctx, tools = make_tools()
    calls = []

    def finalize(_exec, result):
        calls.append(result)
        with pytest.raises(AttributeError):
            result.error = {"message": "forged"}
        return [{"type": "text", "text": "final"}]

    tools.register(canonical_tool(
        "final-fields", lambda _args, _exec: "value", finalize=finalize))
    result = await tools.execute(ToolExecutionInput(
        "c", "final-fields", {}, signal=asyncio.Event()))
    assert result.content == [{"type": "text", "text": "final"}]
    assert result.value == "value" and result.is_error is False and result.error is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_body_error_is_not_misclassified_as_output_error():
    _ctx, tools = make_tools()

    def explode(_args, _exec):
        raise RuntimeError("body broke")

    tools.register(canonical_tool("body-error", explode))
    result = await tools.execute(ToolExecutionInput(
        "c", "body-error", {}, signal=asyncio.Event()))
    assert result.error == {"message": "body broke"}


@pytest.mark.parametrize("schema", [
    {"type": "object", "properties": {}, "required": "x"},
    {"type": "object", "properties": {}, "required": ["missing"]},
    {"type": "string", "enum": []},
    {"type": "string", "enum": [1]},
    {"oneOf": [{"type": "string"}, {"type": "null"}], "const": "x"},
    {"type": "string", "title": 1},
    {"type": "string", "description": False},
])
def test_registration_rejects_unsupported_schema_details(schema):
    _ctx, tools = make_tools()
    definition = canonical_tool("invalid-schema", lambda _args, _exec: "ok")
    definition["output"]["schema"] = schema
    with pytest.raises(TypeError):
        tools.register(definition)


@pytest.mark.asyncio
async def test_invalid_arguments_still_run_snapshotted_finalizer_once():
    ctx, tools = make_tools()
    calls = []

    def finalize(exec, result):
        calls.append((exec.call_id, result.is_error))
        return [{"type": "text", "text": "invalid finalized"}]

    definition = canonical_tool("invalid-args", lambda _args, _exec: "ok", finalize=finalize)
    definition["parameters"] = {
        "type": "object", "properties": {"required": {"type": "string"}},
        "required": ["required"], "additionalProperties": False,
    }
    tools.register(definition)
    result = await tools.execute(ToolExecutionInput(
        "invalid-call", "invalid-args", {}, signal=asyncio.Event()))
    assert result.is_error is True
    assert result.content == [{"type": "text", "text": "invalid finalized"}]
    assert calls == [("invalid-call", True)]


@pytest.mark.asyncio
async def test_cancelled_approval_with_caller_abort_beats_denial():
    ctx, tools = make_tools()
    signal = asyncio.Event()

    class Approval:
        async def request(self, _request):
            signal.set()
            return "cancelled"

    ctx.set_service("approval", Approval())
    agent = SimpleNamespace(ctx=ctx, session=object())
    tools.register(canonical_tool("approval-cancel", lambda _args, _exec: "no"))
    listen(ctx, "tools/pre-execute", lambda _exec, _next: {"kind": "ask"})
    result = await tools.execute(ToolExecutionInput(
        "c", "approval-cancel", {}, agent=agent, signal=signal))
    assert result.error["code"] == "ABORTED_BEFORE_DISPATCH"


@pytest.mark.asyncio
async def test_plugin_owns_service_and_registry_emits_change():
    ctx = Context()
    changes = []
    class SystemPrompt:
        def tools(self, _provider):
            return lambda: None

        def section(self, _section):
            return lambda: None

    ctx.provide("systemPrompt", SystemPrompt())
    listen(ctx, "tools/change", lambda: changes.append("change"))
    fiber = ctx.registry.plugin(ToolsPlugin())
    await fiber
    tools = ctx.get("tools")
    disposer = tools.register_legacy("legacy", "legacy", {}, lambda: "ok")
    disposer()
    assert changes == ["change", "change"]
    await fiber.dispose()
    assert ctx.get("tools", None, strict=False) is None


def test_canonical_registration_validates_contract_and_defaults_exclusive():
    _ctx, tools = make_tools()
    with pytest.raises(TypeError, match="must declare output"):
        tools.register_canonical({
            "name": "bad", "description": "bad", "parameters": {},
            "execute": lambda _args, _exec: None,
        })
    with pytest.raises(TypeError, match="parameters"):
        tools.register({"name": "bad-schema", "description": "bad", "parameters": "no", "execute": lambda: None,
                        "output": {"schema": {}, "render": lambda _a, _v: []}})
    with pytest.raises(TypeError, match="output"):
        tools.register({"name": "bad-output", "description": "bad", "parameters": {}, "execute": lambda: None,
                        "output": {"schema": {}, "render": "no"}})
    with pytest.raises(ValueError, match="timeoutMs"):
        definition = canonical_tool("bad-timeout", lambda _a, _e: "ok")
        definition["timeoutMs"] = True
        tools.register(definition)

    tools.register(canonical_tool("exclusive", lambda _args, _exec: "ok"))
    assert tools.execution_mode(ToolExecutionInput("c", "exclusive", {}, signal=asyncio.Event())) == {"kind": "exclusive"}


@pytest.mark.asyncio
async def test_arguments_reject_non_string_keys_without_silent_collision():
    _ctx, tools = make_tools()
    calls = []
    tools.register(canonical_tool(
        "strict-keys", lambda args, _exec: calls.append(args) or "ok"))

    result = await tools.execute(ToolExecutionInput(
        "c", "strict-keys", {1: "integer-key", "1": "string-key"},
        signal=asyncio.Event()))

    assert result.is_error is True
    assert "losslessly JSON-serializable" in result.error["message"]
    assert calls == []


@pytest.mark.asyncio
async def test_arguments_reject_tuple_as_non_json_container():
    _ctx, tools = make_tools()
    calls = []
    tools.register(canonical_tool(
        "strict-container", lambda args, _exec: calls.append(args) or "ok"))

    result = await tools.execute(ToolExecutionInput(
        "c", "strict-container", {"items": (1, 2)}, signal=asyncio.Event()))

    assert result.is_error is True
    assert "losslessly JSON-serializable" in result.error["message"]
    assert calls == []


@pytest.mark.asyncio
async def test_negative_zero_is_rejected_at_argument_and_output_boundaries():
    _ctx, tools = make_tools()
    calls = []
    definition = canonical_tool(
        "negative-zero", lambda args, _exec: calls.append(args) or -0.0)
    definition["parameters"] = {
        "type": "object", "properties": {"value": {"type": "number"}},
        "required": ["value"], "additionalProperties": False,
    }
    definition["output"]["schema"] = {"type": "number"}
    tools.register(definition)

    bad_arguments = await tools.execute(ToolExecutionInput(
        "a", "negative-zero", {"value": -0.0}, signal=asyncio.Event()))
    assert bad_arguments.is_error is True
    assert "losslessly JSON-serializable" in bad_arguments.error["message"]
    assert calls == []

    bad_output = await tools.execute(ToolExecutionInput(
        "b", "negative-zero", {"value": 0.0}, signal=asyncio.Event()))
    assert bad_output.error["code"] == "INVALID_TOOL_OUTPUT"
    assert calls == [{"value": 0.0}]


def test_registration_accepts_duplicate_required_names_like_upstream():
    _ctx, tools = make_tools()
    definition = canonical_tool("duplicate-required", lambda _args, _exec: "ok")
    definition["parameters"] = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value", "value"],
        "additionalProperties": False,
    }

    tools.register(definition)
    assert tools.get_tool("duplicate-required") is not None


@pytest.mark.asyncio
async def test_scoped_tool_shadows_global_for_only_its_agent():
    ctx, tools = make_tools()
    tools.register(canonical_tool("echo", lambda _args, _exec: "global"))
    first_ctx = ctx.extend()
    second_ctx = ctx.extend()
    first = SimpleNamespace(ctx=first_ctx, session=object())
    second = SimpleNamespace(ctx=second_ctx, session=object())
    first_ctx.tools.register(canonical_tool(
        "echo", lambda _args, _exec: "scoped"))

    scoped = await tools.execute(ToolExecutionInput(
        "a", "echo", {}, agent=first, signal=asyncio.Event()))
    other = await tools.execute(ToolExecutionInput(
        "b", "echo", {}, agent=second, signal=asyncio.Event()))

    assert scoped.value == "scoped"
    assert other.value == "global"
    assert [item["name"] for item in tools.schemas(first)] == ["echo"]


@pytest.mark.asyncio
async def test_scoped_restrict_and_guard_are_agent_isolated_and_disposable():
    ctx, tools = make_tools()
    tools.register(canonical_tool("read", lambda _args, _exec: "read"))
    tools.register(canonical_tool("write", lambda _args, _exec: "write"))
    restricted_ctx = ctx.extend()
    open_ctx = ctx.extend()
    restricted = SimpleNamespace(ctx=restricted_ctx, session=object())
    open_agent = SimpleNamespace(ctx=open_ctx, session=object())

    lift_restrict = restricted_ctx.tools.restrict({"allow": ["read"]})
    lift_guard = restricted_ctx.tools.guard(
        lambda exec_ctx: "read denied" if exec_ctx.name == "read" else None)

    assert [item["name"] for item in tools.schemas(restricted)] == ["read"]
    assert [item["name"] for item in tools.schemas(open_agent)] == ["read", "write"]
    denied = await tools.execute(ToolExecutionInput(
        "a", "read", {}, agent=restricted, signal=asyncio.Event()))
    assert denied.error["message"] == "read denied"
    allowed = await tools.execute(ToolExecutionInput(
        "b", "read", {}, agent=open_agent, signal=asyncio.Event()))
    assert allowed.value == "read"

    lift_guard()
    lift_restrict()
    assert [item["name"] for item in tools.schemas(restricted)] == ["read", "write"]


@pytest.mark.asyncio
async def test_present_as_is_scoped_and_changes_only_that_agents_schema_surface():
    ctx, tools = make_tools()
    ctx.set_service("codeRuntime", SimpleNamespace(language="python"))
    tools.register(canonical_tool("echo", lambda _args, _exec: "ok"))
    coded_ctx = ctx.extend()
    native_ctx = ctx.extend()
    coded = SimpleNamespace(ctx=coded_ctx)
    native = SimpleNamespace(ctx=native_ctx)

    disposer = coded_ctx.tools.present_as("code")

    assert [item["name"] for item in tools.schemas(coded)] == ["run_code"]
    assert [item["name"] for item in tools.schemas(native)] == ["echo"]
    disposer()


def test_present_as_code_mounts_and_disposes_scoped_prompt_sections():
    class SystemPrompt:
        def __init__(self):
            self.sections = []

        def tools(self, _provider):
            return lambda: None

        def section(self, section):
            self.sections.append(section)

            def dispose():
                self.sections.remove(section)

            return dispose

    ctx = Context()
    prompt = SystemPrompt()
    ctx.set_service("systemPrompt", prompt)
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.set_service("codeRuntime", SimpleNamespace(language="python"))
    coded_ctx = ctx.extend()

    dispose = coded_ctx.tools.present_as("code")

    assert [section["name"] for section in prompt.sections] == [
        "tools:code-only", "tools:sdk"]
    dispose()
    assert prompt.sections == []


def test_run_code_schema_tracks_runtime_language():
    runtime = SimpleNamespace(language="python")
    ctx, tools = make_tools({"mode": "both"})
    ctx.set_service("codeRuntime", runtime)

    python_schema = next(item for item in tools.schemas()
                         if item["name"] == "run_code")
    assert "Python program" in python_schema["description"]
    assert "async Python function" in python_schema["parameters"]["properties"]["code"]["description"]

    runtime.language = "typescript"
    typescript_schema = next(item for item in tools.schemas()
                             if item["name"] == "run_code")
    assert "TypeScript program" in typescript_schema["description"]
    assert "async TypeScript function" in typescript_schema["parameters"]["properties"]["code"]["description"]


@pytest.mark.asyncio
@pytest.mark.parametrize("decorated", [
    type("DecoratedDict", (dict,), {})({"value": 1}),
    type("DecoratedList", (list,), {})([1]),
])
async def test_lossless_boundary_rejects_decorated_container_subclasses(decorated):
    _ctx, tools = make_tools()
    calls = []
    tools.register(canonical_tool(
        "plain-only", lambda args, _exec: calls.append(args) or "ok"))

    result = await tools.execute(ToolExecutionInput(
        "c", "plain-only", {"decorated": decorated}, signal=asyncio.Event()))

    assert result.is_error is True
    assert "losslessly JSON-serializable" in result.error["message"]
    assert calls == []


@pytest.mark.asyncio
async def test_deep_schema_value_and_snapshot_do_not_use_python_recursion():
    _ctx, tools = make_tools()
    depth = 1500
    schema = {"type": "string"}
    value = "leaf"
    for _index in range(depth):
        schema = {"type": "array", "items": schema}
        value = [value]
    definition = canonical_tool("deep", lambda _args, _exec: value)
    definition["output"]["schema"] = schema
    definition["output"]["render"] = lambda _args, _value: [
        {"type": "text", "text": "deep"}]

    tools.register(definition)
    result = await tools.execute(ToolExecutionInput(
        "c", "deep", {}, signal=asyncio.Event()))

    assert result.is_error is False
    cursor = result.value
    for _index in range(depth):
        cursor = cursor[0]
    assert cursor == "leaf"


@pytest.mark.asyncio
async def test_code_and_both_surfaces_include_owned_run_code_transport():
    class Runtime:
        language = "python"

        async def run(self, request):
            value = await request["bindings"][0]["functions"]["echo"](
                {"text": "inside"})
            return {"logs": ["runtime log"], "value": value}

    for mode, names in (("code", ["run_code"]),
                        ("both", ["echo", "run_code"])):
        ctx, tools = make_tools({"mode": mode})
        ctx.set_service("codeRuntime", Runtime())
        definition = canonical_tool(
            "echo", lambda args, _exec: args["text"])
        definition["parameters"] = {
            "type": "object", "properties": {"text": {"type": "string"}},
            "required": ["text"], "additionalProperties": False,
        }
        tools.register(definition)
        assert [item["name"] for item in tools.schemas()] == names

        result = await tools.execute(ToolExecutionInput(
            "outer", "run_code",
            {"code": "return await tools.echo({'text': 'inside'})",
             "description": "exercise bridge"}, signal=asyncio.Event()))
        assert result.is_error is False
        assert result.value == {"logs": ["runtime log"], "result": "inside"}
        assert result.content == [{"type": "text", "text": "runtime log\ninside"}]


@pytest.mark.asyncio
async def test_code_mode_direct_native_call_is_collapsed_before_policy():
    ctx, tools = make_tools({"mode": "code"})
    ctx.set_service("codeRuntime", SimpleNamespace(language="python"))
    policy = []
    tools.register(canonical_tool("echo", lambda _args, _exec: "no"))
    listen(ctx, "tools/pre-execute", lambda _exec, _next: policy.append(True))

    result = await tools.execute(ToolExecutionInput(
        "c", "echo", {}, signal=asyncio.Event()))

    assert result.error["code"] == "UNKNOWN_TOOL"
    assert policy == []


@pytest.mark.asyncio
async def test_run_code_bridge_honors_parallel_cap_and_logs_nested_dispatches():
    active = [0]
    peak = [0]

    async def body(args, _exec):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0)
        active[0] -= 1
        return args["value"]

    class Runtime:
        language = "python"

        async def run(self, request):
            call = request["bindings"][0]["functions"]["work"]
            values = await asyncio.gather(
                call({"value": "a"}), call({"value": "b"}))
            return {"logs": [], "value": values}

    class Session:
        def __init__(self):
            self.events = []

        def append(self, name, data):
            self.events.append((name, data))

    ctx, tools = make_tools({"mode": "both", "maxParallelSubCalls": 1})
    ctx.set_service("codeRuntime", Runtime())
    definition = canonical_tool("work", body, safe=lambda _args: True)
    definition["parameters"] = {
        "type": "object", "properties": {"value": {"type": "string"}},
        "required": ["value"], "additionalProperties": False,
    }
    tools.register(definition)
    session = Session()
    agent = SimpleNamespace(ctx=ctx, session=session)

    result = await tools.execute(ToolExecutionInput(
        "outer", "run_code", {"code": "parallel", "description": "parallel"},
        agent=agent, signal=asyncio.Event()))

    assert result.value["result"] == ["a", "b"]
    assert peak == [1]
    assert [name for name, _data in session.events] == [
        "tool/code-dispatch-start", "tool/code-dispatch",
        "tool/code-dispatch-start", "tool/code-dispatch",
    ]
    assert session.events[0][1]["subCallId"] == "outer:code:1"
    assert session.events[2][1]["subCallId"] == "outer:code:2"
