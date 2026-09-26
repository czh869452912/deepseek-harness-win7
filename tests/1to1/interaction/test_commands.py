"""
1:1 parity suite for `@deepseek-ai/dsh-commands`
(`dsh/interaction/commands.py`).

Upstream is reference/packages/interaction/commands/tests/commands.spec.ts
(`describe('parseCommand()')`, `describe('CommandRuntime')`,
`describe('image attachments')`). Every case keeps the upstream setup, action
and assertions: the scoped-layer views, the effect-scoped disposal, the
contained `commands/change` observers, the exact boundary diagnostics, the
`command/run` + `command/done` lifecycle pairing, and the durable image
admission boundary.

Python equivalents of the reference platform values:
* `Object.freeze(x)` -> the port's frozen containers (`FrozenDict`/`FrozenList`),
  asserted by attempting a mutation;
* `AbortController` -> `dsh.core.abort.AbortController` (the shared
  cancellation primitive of `dsh/core/abort.py`);
* `vi.fn()` -> a list of calls captured by a closure.
"""

import asyncio
import base64
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from dsh.attachment.store import AttachmentStore
from dsh.core.abort import AbortController
from dsh.core.agent import Agent
from dsh.core.scope import create_scope
from dsh.core.session import SessionStore
from dsh.core.session.json import FrozenDict, FrozenList
from dsh.cordis.context import Context
from dsh.cordis.logger import Exporter, LoggerLevel
from dsh.interaction.commands import (
    CommandAborted,
    CommandRuntime,
    CommandsPlugin,
    normalize_definition,
    normalize_result,
    parse_command,
)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")


def _command(name: str, text: Optional[str] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "description": f"command {name}",
        "handler": lambda invocation, _text=text if text is not None else f"ran:{name}": {
            "kind": "success",
            "text": _text,
        },
    }


async def mount() -> Context:
    """Mount the store and the registry, exactly like the upstream `mount()`."""
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(CommandsPlugin)
    return ctx


async def mint_agent_scope(ctx: Context, name: str) -> Tuple[Any, Agent]:
    """
    Mint a scope whose key is a live agent, mirroring the upstream
    `mintAgentScope`: the scope is created by a command-injected plugin so the
    scoped context inherits the registry dependency.
    """
    store = ctx.get("sessions")
    session = store.create(name)
    agent = Agent(session=session, ctx=ctx, agent_id=name)
    holder: Dict[str, Any] = {}

    def mint(inner: Context) -> None:
        holder["scope"] = create_scope(inner, agent)

    await ctx.plugin({"apply": mint, "inject": ["commands"]})
    return holder["scope"], agent


def lifecycle_of(agent: Agent) -> List[Dict[str, Any]]:
    """The lifecycle slice of one agent's log (boundary markers stripped)."""
    return [
        {"type": event["type"], "data": dict(event["data"])}
        for event in agent.session.events
        if event["type"] in ("command/run", "command/done")
    ]


def _frozen(value: Any) -> bool:
    """Whether a returned container rejects mutation, like `Object.isFrozen`."""
    if isinstance(value, (FrozenDict, FrozenList)):
        return True
    if isinstance(value, dict):
        try:
            value["__probe__"] = True
        except TypeError:
            return True
        value.pop("__probe__", None)
        return False
    if isinstance(value, (list, tuple)):
        if isinstance(value, tuple):
            return True
        try:
            value.append(1)
        except (TypeError, AttributeError):
            return True
        value.pop()
        return False
    return False


class StoreDouble(AttachmentStore):
    """The upstream `storeOf()` double: real batch admission over stub limits."""

    def __init__(self) -> None:
        super().__init__()
        self.saved = 0
        self.validate_calls = 0
        self.save_calls: List[Dict[str, Any]] = []
        self.fail_with: Optional[BaseException] = None
        self.before_save: Optional[Any] = None

    @property
    def image_limits(self) -> Dict[str, Any]:
        return {
            "maxImageBytes": 1024,
            "maxImagesPerMessage": 2,
            "maxMessageImageBytes": 1024,
            "maxImagePixels": 1_000_000,
            "maxImageDimension": 2000,
            "mediaTypes": ["image/png"],
        }

    def validate_image(self, input_data: Dict[str, Any]) -> None:
        self.validate_calls += 1

    def save_image(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        self.save_calls.append(input_data)
        if self.before_save is not None:
            self.before_save(input_data)
        if self.fail_with is not None:
            raise self.fail_with
        self.saved += 1
        reference: Dict[str, Any] = {
            "attachmentId": f"att-{self.saved}",
            "mediaType": input_data.get("mediaType"),
            "bytes": 3,
            "width": 1,
            "height": 1,
        }
        if input_data.get("name") is not None:
            reference["name"] = input_data["name"]
        return reference


# --------------------------------------------------------------------------
# describe('parseCommand()')
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        ("/goal", {"name": "goal", "rawInput": ""}),
        ("/goal create the thing", {"name": "goal", "rawInput": " create the thing"}),
        ("/goal\ncreate the thing", {"name": "goal", "rawInput": "\ncreate the thing"}),
        ("/goal_name-2\t x ", {"name": "goal_name-2", "rawInput": "\t x "}),
    ],
)
def test_parses_without_normalizing_trailing_input(line, expected):
    """upstream: parses %j without normalizing trailing input."""
    assert parse_command(line) == expected


@pytest.mark.parametrize("line", ["goal", " /goal", "/", "/Goal", "/goal/path", "/goal??"])
def test_rejects_non_command_boundaries(line):
    """upstream: rejects non-command boundary %j."""
    assert parse_command(line) is None


# --------------------------------------------------------------------------
# describe('CommandRuntime')
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lists_immutable_global_descriptors_with_input_metadata():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register({
        "name": "inspect",
        "description": "Inspect state",
        "input": {"hint": "<target>"},
        "handler": lambda invocation: {"kind": "success"},
    })

    listed = ctx.commands.list(agent)
    assert [descriptor.to_dict() for descriptor in listed] == [
        {"name": "inspect", "description": "Inspect state", "input": {"hint": "<target>"}}
    ]
    assert _frozen(listed)
    assert _frozen(listed[0].input)
    assert ctx.commands.find(agent, "inspect").name == "inspect"
    assert ctx.commands.find(agent, "missing") is None


@pytest.mark.asyncio
async def test_sorts_distinct_effective_command_names():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(_command("zeta"))
    ctx.commands.register(_command("alpha"))
    ctx.commands.register(_command("middle"))
    assert [item.name for item in ctx.commands.list(agent)] == ["alpha", "middle", "zeta"]


@pytest.mark.asyncio
async def test_uses_agent_scoped_shadows_and_removes_them_with_their_scope():
    ctx = await mount()
    scope, agent = await mint_agent_scope(ctx, "a")
    other = Agent(session=ctx.get("sessions").create("other"), ctx=ctx, agent_id="other")
    ctx.commands.register(_command("shared", "global"))
    scope.ctx.commands.register(_command("shared", "scoped"))

    assert [item.name for item in ctx.commands.list(agent)] == ["shared"]
    assert ctx.commands.find(agent, "shared").handler is not None
    assert [item.name for item in ctx.commands.list(other)] == ["shared"]
    execution = await ctx.commands.execute(agent, "/shared", [], AbortController().signal)
    assert dict(execution.result) == {"kind": "success", "text": "scoped"}

    await scope.dispose()
    after = await ctx.commands.execute(agent, "/shared", [], AbortController().signal)
    assert after.result["text"] == "global"


@pytest.mark.asyncio
async def test_removes_a_registration_when_its_contributing_plugin_fiber_is_disposed():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")

    def contribute(inner: Context) -> None:
        inner.commands.register(_command("temporary"))

    fiber = await ctx.plugin({"apply": contribute, "inject": ["commands"]})
    assert ctx.commands.find(agent, "temporary") is not None

    await fiber.dispose()

    assert ctx.commands.find(agent, "temporary") is None


@pytest.mark.asyncio
async def test_rejects_duplicates_within_one_layer_while_allowing_a_scoped_shadow():
    ctx = await mount()
    scope, _agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(_command("same"))
    with pytest.raises(RuntimeError, match=r"agent\.ctx"):
        ctx.commands.register(_command("same"))
    scope.ctx.commands.register(_command("same"))
    with pytest.raises(RuntimeError, match="already registered in this scope"):
        scope.ctx.commands.register(_command("same"))


@pytest.mark.asyncio
async def test_notifies_on_registration_and_disposal_while_containing_broken_observers():
    ctx = await mount()
    changed: List[str] = []
    ctx.on("commands/change", lambda: changed.append("initial"))
    dispose = ctx.commands.register(_command("live"))
    dispose()
    dispose()
    assert len(changed) == 2

    after_failures: List[str] = []
    captured: List[str] = []
    ctx.logger.exporter(
        Exporter(
            export_fn=lambda message: captured.append(message.args[0] if message.args else ""),
            colors=0,
            levels={"default": LoggerLevel.DEBUG},
        )
    )

    def observer_threw() -> None:
        raise RuntimeError("observer threw")

    def observer_rejected() -> Any:
        async def rejected() -> None:
            raise RuntimeError("observer rejected")

        return rejected()

    ctx.on("commands/change", observer_threw)
    ctx.on("commands/change", observer_rejected)
    ctx.on("commands/change", lambda: after_failures.append("after"))
    remove_contained = ctx.commands.register(_command("contained"))
    _scope, agent = await mint_agent_scope(ctx, "a")
    assert ctx.commands.find(agent, "contained") is not None
    assert len(after_failures) == 1

    for _ in range(50):
        if (
            "commands/change listener threw: observer threw" in captured
            and "commands/change listener rejected: observer rejected" in captured
        ):
            break
        await asyncio.sleep(0.01)
    assert "commands/change listener threw: observer threw" in captured
    assert "commands/change listener rejected: observer rejected" in captured

    remove_contained()
    assert ctx.commands.find(agent, "contained") is None
    assert len(after_failures) == 2


@pytest.mark.asyncio
async def test_rejects_non_string_descriptions_and_input_hints_with_boundary_diagnostics():
    ctx = await mount()
    with pytest.raises(TypeError, match='command "description-type" description must be a string'):
        ctx.commands.register({**_command("description-type"), "description": None})
    with pytest.raises(TypeError, match='command "hint-type" input hint must be a string'):
        ctx.commands.register({**_command("hint-type"), "input": {"hint": 42}})
    with pytest.raises(TypeError, match='command "input-type" input hint must be a string'):
        ctx.commands.register({**_command("input-type"), "input": None})


@pytest.mark.asyncio
async def test_passes_exact_invocation_context_and_detaches_valid_handler_results():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    seen: List[Any] = []

    def handler(invocation: Any) -> Dict[str, Any]:
        seen.append(invocation)
        return {"kind": "success", "text": "ok"}

    ctx.commands.register({"name": "run", "description": "Run it", "handler": handler})
    controller = AbortController()

    execution = await ctx.commands.execute(agent, "/run  untouched ", [], controller.signal)

    assert dict(execution.result) == {"kind": "success", "text": "ok"}
    assert execution.command_id
    assert _frozen(execution.result)
    assert seen[0].agent is agent
    assert seen[0].raw_input == "  untouched "
    assert seen[0].signal is controller.signal
    assert await ctx.commands.execute(agent, "run", [], controller.signal) is None
    assert await ctx.commands.execute(agent, "/missing", [], controller.signal) is None


@pytest.mark.asyncio
async def test_stops_awaiting_an_aborted_handler_and_handles_an_already_aborted_signal():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    release: Dict[str, Any] = {}

    def wait_handler(invocation: Any) -> Any:
        async def pending() -> Dict[str, Any]:
            future: "asyncio.Future[Any]" = asyncio.get_event_loop().create_future()
            release["settle"] = future
            return await future

        return pending()

    ctx.commands.register({"name": "wait", "description": "Wait", "handler": wait_handler})
    running = AbortController()
    promise = asyncio.ensure_future(ctx.commands.execute(agent, "/wait", [], running.signal))
    await asyncio.sleep(0.02)
    running.abort("operator cancelled command")
    with pytest.raises(CommandAborted) as raised:
        await promise
    assert str(raised.value) == "operator cancelled command"
    # The uncooperative handler is detached, not cancelled: it can still settle.
    release["settle"].set_result({"kind": "success", "text": "late"})
    await asyncio.sleep(0.02)

    already = AbortController()
    already.abort(RuntimeError("already gone"))
    with pytest.raises(RuntimeError, match="already gone"):
        await ctx.commands.execute(agent, "/wait", [], already.signal)

    default_reason = AbortController()
    default_reason.abort({"source": "test"})
    with pytest.raises(CommandAbortedAlias, match="command aborted"):
        await ctx.commands.execute(agent, "/wait", [], default_reason.signal)


@pytest.mark.asyncio
async def test_propagates_an_asynchronously_rejected_handler():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")

    def reject(invocation: Any) -> Any:
        async def rejected() -> Any:
            raise RuntimeError("handler rejected")

        return rejected()

    ctx.commands.register({"name": "reject", "description": "Reject", "handler": reject})
    with pytest.raises(RuntimeError, match="handler rejected"):
        await ctx.commands.execute(agent, "/reject", [], AbortController().signal)

    # A non-Error rejection and a hostile `toString` have no Python equivalent:
    # Python rejects only with BaseException subclasses, and their rendering is
    # contained by the same `renderThrown` equivalent the reference uses.
    class Hostile(RuntimeError):
        def __str__(self) -> str:
            raise RuntimeError("cannot render")

    hostile = Hostile("unused")
    assert normalize_result("reject-hostile", {"kind": "success"}) == {"kind": "success"}

    def reject_hostile(invocation: Any) -> Any:
        async def rejected() -> Any:
            raise hostile

        return rejected()

    ctx.commands.register(
        {"name": "reject-hostile", "description": "Reject an unrenderable value", "handler": reject_hostile}
    )
    with pytest.raises(Hostile):
        await ctx.commands.execute(agent, "/reject-hostile", [], AbortController().signal)
    done = lifecycle_of(agent)[-1]
    assert done["data"]["kind"] == "error"
    assert done["data"]["text"] == "<unrenderable thrown value>"


@pytest.mark.asyncio
async def test_observes_an_abort_triggered_synchronously_inside_the_handler():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    controller = AbortController()

    def self_abort(invocation: Any) -> Dict[str, Any]:
        controller.abort("aborted in handler")
        return {"kind": "success"}

    ctx.commands.register(
        {"name": "self-abort", "description": "Abort before returning", "handler": self_abort}
    )
    with pytest.raises(CommandAbortedAlias, match="aborted in handler"):
        await ctx.commands.execute(agent, "/self-abort", [], controller.signal)


@pytest.mark.asyncio
async def test_returns_a_detached_expected_error_result():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(
        {"name": "denied", "description": "Denied", "handler": lambda i: {"kind": "error", "text": "not now"}}
    )
    execution = await ctx.commands.execute(agent, "/denied", [], AbortController().signal)
    assert dict(execution.result) == {"kind": "error", "text": "not now"}
    assert _frozen(execution.result)

    ctx.commands.register(
        {"name": "silent", "description": "No output", "handler": lambda i: {"kind": "success"}}
    )
    silent = await ctx.commands.execute(agent, "/silent", [], AbortController().signal)
    assert dict(silent.result) == {"kind": "success"}
    assert _frozen(silent.result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "definition,expected",
    [
        ({**_command("Bad")}, "command name"),
        ({**_command("empty-description"), "description": " "}, "description"),
        ({**_command("empty-hint"), "input": {"hint": ""}}, "input hint"),
        ({**_command("bad-handler"), "handler": None}, "handler"),
    ],
)
async def test_rejects_invalid_definitions(definition, expected):
    ctx = await mount()
    with pytest.raises(TypeError, match=expected):
        ctx.commands.register(definition)


@pytest.mark.asyncio
async def test_logs_a_paired_command_run_and_done_around_a_successful_handler():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(_command("deploy", "deployed"))

    execution = await ctx.commands.execute(agent, "/deploy now", [], AbortController().signal)

    lifecycle = lifecycle_of(agent)
    assert lifecycle[0]["type"] == "command/run"
    assert lifecycle[0]["data"]["name"] == "deploy"
    assert lifecycle[0]["data"]["args"] == " now"
    assert lifecycle[0]["data"]["source"] == {"kind": "user"}
    assert lifecycle[1]["type"] == "command/done"
    assert lifecycle[1]["data"]["kind"] == "success"
    assert lifecycle[1]["data"]["text"] == "deployed"
    assert lifecycle[0]["data"]["commandId"] == lifecycle[1]["data"]["commandId"]
    assert execution.command_id == lifecycle[0]["data"]["commandId"]
    # Direct log-only appends: no turn is opened for the pair on an idle log.
    assert [event["type"] for event in agent.session.events] == ["command/run", "command/done"]


@pytest.mark.asyncio
async def test_preserves_an_earlier_authoritative_domain_event_reference():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    source = agent.session.append("turn/start", {"turn": 1})
    ctx.commands.register({
        "name": "linked",
        "description": "Link outcome",
        "handler": lambda i: {"kind": "success", "text": "linked", "sourceEventSeq": source["seq"]},
    })

    execution = await ctx.commands.execute(agent, "/linked", [], AbortController().signal)

    assert dict(execution.result) == {"kind": "success", "text": "linked", "sourceEventSeq": source["seq"]}
    done = lifecycle_of(agent)[1]
    assert done["data"]["kind"] == "success"
    assert done["data"]["text"] == "linked"
    assert done["data"]["sourceEventSeq"] == source["seq"]


@pytest.mark.asyncio
async def test_omits_raw_input_from_command_run_when_a_domain_event_owns_it():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    seen: List[Any] = []
    ctx.commands.register({
        "name": "private",
        "description": "Record privately",
        "recordInput": False,
        "handler": lambda invocation: seen.append(invocation) or {"kind": "success"},
    })

    await ctx.commands.execute(agent, "/private keep this once", [], AbortController().signal)

    assert seen[0].raw_input == " keep this once"
    run = next(event for event in agent.session.events if event["type"] == "command/run")
    assert "args" not in run["data"]


@pytest.mark.asyncio
async def test_mints_distinct_monotonic_command_ids_across_executions():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(_command("first"))
    ctx.commands.register(_command("second"))
    await ctx.commands.execute(agent, "/first", [], AbortController().signal)
    await ctx.commands.execute(agent, "/second", [], AbortController().signal)
    ids = [event["data"]["commandId"] for event in lifecycle_of(agent) if event["type"] == "command/run"]
    assert len(set(ids)) == 2


@pytest.mark.asyncio
async def test_logs_done_kind_error_for_an_expected_error_result():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(
        {"name": "denied", "description": "Denied", "handler": lambda i: {"kind": "error", "text": "not now"}}
    )
    await ctx.commands.execute(agent, "/denied", [], AbortController().signal)
    done = lifecycle_of(agent)[1]
    assert done["type"] == "command/done"
    assert done["data"]["kind"] == "error"
    assert done["data"]["text"] == "not now"


@pytest.mark.asyncio
async def test_logs_done_kind_error_when_the_handler_throws_and_preserves_the_throw():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")

    def boom(invocation: Any) -> Any:
        raise RuntimeError("handler exploded")

    ctx.commands.register({"name": "boom", "description": "Throw", "handler": boom})
    with pytest.raises(RuntimeError, match="handler exploded"):
        await ctx.commands.execute(agent, "/boom", [], AbortController().signal)
    done = lifecycle_of(agent)[1]
    assert done["data"]["kind"] == "error"
    assert done["data"]["text"] == "handler exploded"


@pytest.mark.asyncio
async def test_logs_done_kind_error_when_the_signal_aborts_a_hanging_handler():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")

    def hang(invocation: Any) -> Any:
        async def never() -> None:
            forever: "asyncio.Future[None]" = asyncio.get_event_loop().create_future()
            await forever

        return never()

    ctx.commands.register({"name": "hang", "description": "Hang", "handler": hang})
    controller = AbortController()
    pending = asyncio.ensure_future(ctx.commands.execute(agent, "/hang", [], controller.signal))
    # The run append must land before the abort so the pair stays complete.
    for _ in range(50):
        if len(lifecycle_of(agent)) == 1:
            break
        await asyncio.sleep(0.01)
    assert len(lifecycle_of(agent)) == 1
    controller.abort("operator cancelled command")
    with pytest.raises(CommandAbortedAlias, match="operator cancelled command"):
        await pending
    for _ in range(50):
        if len(lifecycle_of(agent)) == 2:
            break
        await asyncio.sleep(0.01)
    done = lifecycle_of(agent)[1]
    assert done["type"] == "command/done"
    assert done["data"]["kind"] == "error"
    assert done["data"]["text"] == "operator cancelled command"


@pytest.mark.asyncio
async def test_logs_nothing_for_admission_misses():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(_command("real"))
    signal = AbortController().signal
    await ctx.commands.execute(agent, "not a command", [], signal)
    await ctx.commands.execute(agent, "/missing", [], signal)
    assert agent.session.events == []


@pytest.mark.asyncio
async def test_joins_an_open_turn_without_wrapping_the_lifecycle_pair():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(_command("mid"))
    agent.session.append("turn/start", {"turn": 1})
    await ctx.commands.execute(agent, "/mid", [], AbortController().signal)
    assert [event["type"] for event in agent.session.events] == [
        "turn/start",
        "command/run",
        "command/done",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output,expected",
    [
        (None, "CommandResult"),
        ({}, "CommandResult"),
        ({"kind": "success", "text": 1}, "success text"),
        ({"kind": "success", "sourceEventSeq": -1}, "sourceEventSeq"),
        ({"kind": "success", "sourceEventSeq": 1.5}, "sourceEventSeq"),
        ({"kind": "success", "sourceEventSeq": "1"}, "sourceEventSeq"),
        ({"kind": "error", "text": ""}, "error text"),
        ({"kind": "error", "text": 1}, "error text"),
        ({"kind": "future", "text": "x"}, "unknown result kind"),
    ],
)
async def test_rejects_malformed_handler_results(output, expected):
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register({"name": "broken", "description": "Broken", "handler": lambda i: output})
    with pytest.raises(TypeError, match=expected):
        await ctx.commands.execute(agent, "/broken", [], AbortController().signal)


# --------------------------------------------------------------------------
# describe('image attachments')
# --------------------------------------------------------------------------


def accepting(handler: Any) -> Dict[str, Any]:
    return {
        "name": "vision",
        "description": "accepts images",
        "input": {"hint": "<objective>", "images": True},
        "handler": handler,
    }


@pytest.mark.asyncio
async def test_rejects_a_boolean_typed_images_flag_violation_at_registration():
    ctx = await mount()
    with pytest.raises(TypeError, match='command "flag-type" input images flag must be a boolean'):
        ctx.commands.register({**_command("flag-type"), "input": {"hint": "x", "images": "yes"}})


@pytest.mark.asyncio
async def test_lists_images_acceptance_on_the_descriptor_and_omits_a_false_flag():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(accepting(lambda i: {"kind": "success"}))
    ctx.commands.register({**_command("plain-input"), "input": {"hint": "x", "images": False}})
    by_name = {descriptor.name: descriptor for descriptor in ctx.commands.list(agent)}
    assert dict(by_name["vision"].input) == {"hint": "<objective>", "images": True}
    assert dict(by_name["plain-input"].input) == {"hint": "x"}


@pytest.mark.asyncio
async def test_settles_images_sent_to_a_non_declaring_command_as_a_logged_error():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    calls: List[Any] = []
    ctx.commands.register({**_command("deploy"), "handler": lambda i: calls.append(i) or {"kind": "success"}})
    execution = await ctx.commands.execute(
        agent, "/deploy now", [{"mediaType": "image/png", "data": PNG}], AbortController().signal
    )
    assert dict(execution.result) == {
        "kind": "error",
        "text": "/deploy does not accept image attachments",
    }
    assert calls == []
    done = lifecycle_of(agent)[1]
    assert done["data"]["kind"] == "error"
    assert done["data"]["text"] == "/deploy does not accept image attachments"


@pytest.mark.asyncio
async def test_settles_a_declaring_command_as_a_logged_error_without_an_attachment_store():
    ctx = await mount()
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(accepting(lambda i: {"kind": "success"}))
    execution = await ctx.commands.execute(
        agent, "/vision x", [{"mediaType": "image/png", "data": PNG}], AbortController().signal
    )
    assert dict(execution.result) == {
        "kind": "error",
        "text": "/vision: image attachments are unavailable because no attachment store is composed",
    }


@pytest.mark.asyncio
async def test_admits_and_hands_the_handler_frozen_ordered_image_blocks():
    ctx = await mount()
    store = StoreDouble()
    ctx.set_service("attachments", store)
    _scope, agent = await mint_agent_scope(ctx, "a")
    seen: List[Any] = []

    def handler(invocation: Any) -> Dict[str, Any]:
        assert _frozen(invocation.attachments)
        seen.append(invocation)
        return {"kind": "success"}

    ctx.commands.register(accepting(handler))
    await ctx.commands.execute(
        agent,
        "/vision x",
        [
            {"mediaType": "image/png", "data": PNG, "name": "a.png"},
            {"mediaType": "image/png", "data": PNG, "name": "b.png"},
        ],
        AbortController().signal,
    )
    assert [
        (block["type"], block["attachment"]["name"]) for block in seen[0].attachments
    ] == [("image", "a.png"), ("image", "b.png")]

    await ctx.commands.execute(agent, "/vision y", [], AbortController().signal)
    assert list(seen[1].attachments) == []


@pytest.mark.asyncio
async def test_settles_an_admission_limit_failure_as_a_logged_error_result():
    ctx = await mount()
    ctx.set_service("attachments", StoreDouble())
    _scope, agent = await mint_agent_scope(ctx, "a")
    calls: List[Any] = []
    ctx.commands.register(accepting(lambda i: calls.append(i) or {"kind": "success"}))
    three = [{"mediaType": "image/png", "data": PNG} for _ in range(3)]
    execution = await ctx.commands.execute(agent, "/vision x", three, AbortController().signal)
    assert dict(execution.result) == {
        "kind": "error",
        "text": "Image batch exceeds the configured image-count limit.",
    }
    assert calls == []
    done = lifecycle_of(agent)[-1]
    assert done["type"] == "command/done"
    assert done["data"]["kind"] == "error"


@pytest.mark.asyncio
async def test_honors_a_cancellation_that_lands_during_admission_before_the_handler():
    ctx = await mount()
    controller = AbortController()
    store = StoreDouble()
    def cancel_during_admission(input_data: Dict[str, Any]) -> None:
        controller.abort("operator cancelled during admission")

    store.before_save = cancel_during_admission
    ctx.set_service("attachments", store)
    _scope, agent = await mint_agent_scope(ctx, "a")
    calls: List[Any] = []
    ctx.commands.register(accepting(lambda i: calls.append(i) or {"kind": "success"}))

    with pytest.raises(CommandAbortedAlias, match="operator cancelled during admission"):
        await ctx.commands.execute(
            agent, "/vision x", [{"mediaType": "image/png", "data": PNG}], controller.signal
        )

    assert calls == []
    done = lifecycle_of(agent)[-1]
    assert done["type"] == "command/done"
    assert done["data"]["kind"] == "error"
    assert done["data"]["text"] == "operator cancelled during admission"


@pytest.mark.asyncio
async def test_logs_and_rethrows_a_non_attachment_admission_failure():
    ctx = await mount()
    store = StoreDouble()
    store.fail_with = RuntimeError("disk gone")
    ctx.set_service("attachments", store)
    _scope, agent = await mint_agent_scope(ctx, "a")
    ctx.commands.register(accepting(lambda i: {"kind": "success"}))

    with pytest.raises(RuntimeError, match="disk gone"):
        await ctx.commands.execute(
            agent, "/vision x", [{"mediaType": "image/png", "data": PNG}], AbortController().signal
        )

    done = lifecycle_of(agent)[-1]
    assert done["type"] == "command/done"
    assert done["data"]["kind"] == "error"
    assert done["data"]["text"] == "disk gone"


# --------------------------------------------------------------------------
# package-level boundary helpers
# --------------------------------------------------------------------------


def test_normalize_definition_matches_the_reference_boundary_diagnostics():
    """
    The reference `COMMAND_NAME` interpolated into the name diagnostic is
    `String(/^[a-z][a-z0-9_-]*$/u)`.
    """
    with pytest.raises(TypeError) as raised:
        normalize_definition({"name": "Bad", "description": "d", "handler": lambda i: None})
    assert str(raised.value) == 'command name "Bad" must match /^[a-z][a-z0-9_-]*$/u'


def test_normalize_result_rejects_an_unsafe_source_event_seq():
    with pytest.raises(TypeError, match="sourceEventSeq"):
        normalize_result("x", {"kind": "success", "sourceEventSeq": 1.5})


def test_the_package_default_export_is_the_registry_the_loader_unwraps():
    """
    The package's default export is the registry class, exactly like the
    reference `export default CommandRuntime`, so the Loader's `unwrapExports`
    answers the mountable row class for the module.
    """
    from dsh.cordis.loader import Loader

    import dsh.interaction.commands as module

    loader = Loader(Context())
    assert loader.unwrap_exports(module) is module.default
    assert module.default is CommandRuntime


import dsh.interaction.commands as _commands_module  # noqa: E402

CommandAbortedAlias = _commands_module.CommandAborted
CommandRuntimeAlias = CommandRuntime
json_dumps = json.dumps


@pytest.mark.asyncio
async def test_the_permission_presets_row_registers_its_command_through_the_registry():
    """
    Cross-module check for the consumer that already passed a canonical
    `CommandDefinition`: mounting `@deepseek-ai/dsh-permission-presets` beside
    `@deepseek-ai/dsh-commands` registers `/permission`, and executing it
    through the registry reaches the preset service. Before the canonical
    registry port this registration raised (the old signature took
    `(name, description, handler)`).
    """
    from dsh.interaction.permission_presets import PermissionPresetsPlugin

    ctx = await mount()
    await ctx.plugin(PermissionPresetsPlugin)
    session = ctx.get("sessions").create("permission-session")
    agent = Agent(session=session, ctx=ctx, agent_id="permission-session")

    descriptor = {d.name: d for d in ctx.commands.list(agent)}["permission"]
    assert descriptor.to_dict() == {
        "name": "permission",
        "description": "Switch the permission preset (sandbox mode + approval policy)",
        "input": {"hint": "<preset>"},
    }

    execution = await ctx.commands.execute(agent, "/permission", [], AbortController().signal)
    assert execution.result["kind"] == "success"
    assert "current preset workspace-write" in execution.result["text"]

    switched = await ctx.commands.execute(
        agent, "/permission danger-full-access", [], AbortController().signal
    )
    assert dict(switched.result) == {"kind": "success", "text": "preset danger-full-access"}
    recorded = [
        event["data"]["preset"]
        for event in session.events
        if event["type"] == "permission/preset"
    ]
    assert recorded[-1] == "danger-full-access"
    assert recorded.count("danger-full-access") == 1
