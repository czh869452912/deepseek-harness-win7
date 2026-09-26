"""
1:1 parity suite for `@deepseek-ai/dsh-command-feedback`
(`dsh/feedback/command_feedback.py`).

Upstream is reference/packages/feedback/command-feedback/tests/
command-feedback.spec.ts and .../loader-composition.spec.ts. Every case keeps
the upstream setup, action and assertions: the registered command definition,
the acknowledgement and its session-sharing disclosure, the authoritative
`feedback/record` payload, the empty-input rejection, cancellation, and the
model-invisibility of every recorded event.

The upstream suite mocks `@deepseek-ai/dsh-anonymous-user-id` so the
acknowledgement is deterministic; here the real producer runs against a
temporary `$DSH_HOME`, and the expected id is the same producer's own value for
that home (the fixture, not the module, owns the expectation).
"""

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, List, Optional

import pytest

from dsh.boot.app_boot import boot
from dsh.core.abort import AbortController
from dsh.core.agent import Agent
from dsh.core.session import SessionStore
from dsh.core.session.surface import SURFACE_EVENT_TYPES
from dsh.core.surface import derive_event_message, fold_surface
from dsh.cordis.context import Context
from dsh.identity.anonymous_user_id import get_or_create_anonymous_user_id
from dsh.interaction.commands import CommandsPlugin
from dsh.feedback import command_feedback
from dsh.feedback.command_feedback import CommandFeedbackPlugin


class FakeTelemetry:
    """Minimal mounted backend disclosing one sharing policy."""

    def __init__(self, sharing: str) -> None:
        self.sharing = sharing


async def harness(sharing: Optional[str] = None) -> Dict[str, Any]:
    """
    Mount the real command registry, this producer, and optionally a telemetry
    backend disclosing one sharing policy. Without `sharing`, no telemetry
    service exists and the acknowledgement reports "not configured".
    """
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(CommandsPlugin)
    if sharing is not None:
        ctx.set_service("sessionTelemetry", FakeTelemetry(sharing))
    plugin = await ctx.plugin(CommandFeedbackPlugin)
    session = ctx.get("sessions").create("command-feedback")
    agent = Agent(session=session, ctx=ctx, agent_id="command-feedback")
    return {"ctx": ctx, "agent": agent, "session": session, "plugin": plugin}


async def run(test: Dict[str, Any], suffix: str = "", signal: Any = None) -> Dict[str, Any]:
    """Execute `/feedback` through the same registry boundary as a UI adapter."""
    settled = await test["ctx"].commands.execute(
        test["agent"], f"/feedback{suffix}", [], signal or AbortController().signal
    )
    assert settled is not None, "feedback command was not registered"
    return dict(settled.result)


def feedback_texts(session: Any) -> List[str]:
    """Authoritative feedback payloads in log order."""
    return [
        event["data"]["text"] for event in session.events if event["type"] == "feedback/record"
    ]


@pytest.mark.asyncio
async def test_registers_one_global_command_with_loader_safe_exports_and_disposes_it():
    test = await harness()
    assert command_feedback.name == "command-feedback"
    assert command_feedback.inject == ["commands"]
    # The package is a plugin module: the Loader's `unwrapExports` answers the
    # module itself, so `default` is the only export the port must not add.
    assert not hasattr(command_feedback, "default")
    from dsh.cordis.context import Context as _Context
    from dsh.cordis.loader import Loader

    loader = Loader(_Context())
    assert loader.unwrap_exports(command_feedback) is command_feedback

    listed = [descriptor.to_dict() for descriptor in test["ctx"].commands.list(test["agent"])]
    assert {
        "name": "feedback",
        "description": "record feedback about this session",
        "input": {"hint": "<text>"},
    } in listed
    assert test["ctx"].commands.find(test["agent"], "feedback").record_input is False

    await test["plugin"].dispose()
    assert test["ctx"].commands.find(test["agent"], "feedback") is None


@pytest.mark.asyncio
async def test_acknowledges_feedback_and_records_its_payload_exactly_once():
    home = tempfile.mkdtemp(prefix="dsh-command-feedback-")
    os.environ["DSH_HOME"] = home
    try:
        user_id = get_or_create_anonymous_user_id({"env": {"DSH_HOME": home}})
        test = await harness()
        assert await run(test, " the diff view is unreadable") == {
            "kind": "success",
            "text": (
                f"Feedback recorded for session {test['session'].id}\n"
                f"Anonymous user: {user_id}. Session sharing is not configured."
            ),
        }
        assert feedback_texts(test["session"]) == ["the diff view is unreadable"]
        run_event = next(
            event for event in test["session"].events if event["type"] == "command/run"
        )
        assert "args" not in run_event["data"]
        assert json.dumps(
            [dict(event) for event in test["session"].events], default=str
        ).count("the diff view is unreadable") == 1
    finally:
        os.environ.pop("DSH_HOME", None)


@pytest.mark.asyncio
async def test_exports_a_command_independent_feedback_producer():
    test = await harness()
    command_feedback.record_feedback(test["session"], "  recorded outside a command  ")
    assert [event["type"] for event in test["session"].events] == ["feedback/record"]
    assert feedback_texts(test["session"]) == ["recorded outside a command"]
    with pytest.raises(TypeError, match="feedback text must not be empty"):
        command_feedback.record_feedback(test["session"], " \n\t ")
    assert feedback_texts(test["session"]) == ["recorded outside a command"]


@pytest.mark.asyncio
async def test_keeps_command_bookkeeping_around_the_authoritative_feedback_event():
    test = await harness()
    await run(test, " nothing else happens")
    assert [event["type"] for event in test["session"].events] == [
        "command/run",
        "feedback/record",
        "command/done",
    ]


@pytest.mark.asyncio
async def test_normalizes_surrounding_whitespace_without_parsing_command_like_content():
    test = await harness()
    await run(test, " /plan felt SLOW\n\ttwice today ")
    assert feedback_texts(test["session"]) == ["/plan felt SLOW\n\ttwice today"]


@pytest.mark.asyncio
async def test_records_each_entry_separately_without_replacing_earlier_ones():
    test = await harness()
    await run(test, " first")
    await run(test, " second")
    assert feedback_texts(test["session"]) == ["first", "second"]


@pytest.mark.asyncio
async def test_records_concurrent_submissions_in_dispatch_order():
    home = tempfile.mkdtemp(prefix="dsh-command-feedback-")
    os.environ["DSH_HOME"] = home
    try:
        user_id = get_or_create_anonymous_user_id({"env": {"DSH_HOME": home}})
        test = await harness()
        signal = AbortController().signal
        # Command adapters may dispatch concurrent requests without awaiting one another.
        settled = await asyncio.gather(
            test["ctx"].commands.execute(test["agent"], "/feedback first", [], signal),
            test["ctx"].commands.execute(test["agent"], "/feedback second", [], signal),
        )
        acknowledgement = {
            "kind": "success",
            "text": (
                f"Feedback recorded for session {test['session'].id}\n"
                f"Anonymous user: {user_id}. Session sharing is not configured."
            ),
        }
        assert [dict(item.result) for item in settled] == [acknowledgement, acknowledgement]
        assert feedback_texts(test["session"]) == ["first", "second"]
    finally:
        os.environ.pop("DSH_HOME", None)


@pytest.mark.asyncio
async def test_discloses_full_session_sharing_in_the_acknowledgement():
    home = tempfile.mkdtemp(prefix="dsh-command-feedback-")
    os.environ["DSH_HOME"] = home
    try:
        user_id = get_or_create_anonymous_user_id({"env": {"DSH_HOME": home}})
        test = await harness("full")
        assert await run(test, " everything shared") == {
            "kind": "success",
            "text": (
                f"Feedback recorded for session {test['session'].id}\n"
                f"Anonymous user: {user_id}. Session sharing is enabled."
            ),
        }
        assert feedback_texts(test["session"]) == ["everything shared"]
    finally:
        os.environ.pop("DSH_HOME", None)


@pytest.mark.asyncio
async def test_discloses_feedback_gated_session_sharing_in_the_acknowledgement():
    home = tempfile.mkdtemp(prefix="dsh-command-feedback-")
    os.environ["DSH_HOME"] = home
    try:
        user_id = get_or_create_anonymous_user_id({"env": {"DSH_HOME": home}})
        test = await harness("feedback-only")
        assert await run(test, " gated sharing") == {
            "kind": "success",
            "text": (
                f"Feedback recorded for session {test['session'].id}\n"
                f"Anonymous user: {user_id}. Session sharing is feedback-gated; "
                "recording feedback uploads the session records not yet shared."
            ),
        }
        assert feedback_texts(test["session"]) == ["gated sharing"]
    finally:
        os.environ.pop("DSH_HOME", None)


@pytest.mark.asyncio
async def test_discloses_disabled_session_sharing_in_the_acknowledgement():
    home = tempfile.mkdtemp(prefix="dsh-command-feedback-")
    os.environ["DSH_HOME"] = home
    try:
        user_id = get_or_create_anonymous_user_id({"env": {"DSH_HOME": home}})
        test = await harness("disabled")
        assert await run(test, " local only") == {
            "kind": "success",
            "text": (
                f"Feedback recorded for session {test['session'].id}\n"
                f"Anonymous user: {user_id}. Session sharing is disabled."
            ),
        }
        assert feedback_texts(test["session"]) == ["local only"]
    finally:
        os.environ.pop("DSH_HOME", None)


@pytest.mark.asyncio
async def test_keeps_every_recorded_event_out_of_model_context_and_derived_history():
    test = await harness()
    await run(test, " invisible to the model")
    session = test["session"]
    for event in session.events:
        assert "surfaceOp" not in event
        assert session.derive_event_message(event) is None
    assert fold_surface(session.events).nodes == []
    assert session.surface.nodes == []
    assert session.derive_messages() == []


@pytest.mark.asyncio
async def test_rejects_empty_and_whitespace_only_input_as_a_failed_command_record():
    test = await harness()
    expected = {
        "kind": "error",
        "text": "Feedback text is required. Usage: /feedback <text>",
    }
    assert await run(test) == expected
    assert await run(test, "   \n\t ") == expected
    assert feedback_texts(test["session"]) == []
    done = [event for event in test["session"].events if event["type"] == "command/done"]
    assert [event["data"]["kind"] for event in done] == ["error", "error"]
    for event in test["session"].events:
        if event["type"] == "command/run":
            assert "args" not in event["data"]


@pytest.mark.asyncio
async def test_records_nothing_when_dispatch_rejects_an_already_cancelled_request():
    test = await harness()
    controller = AbortController()
    controller.abort(RuntimeError("user cancelled the command"))
    with pytest.raises(RuntimeError, match="user cancelled the command"):
        await test["ctx"].commands.execute(test["agent"], "/feedback too late", [], controller.signal)
    assert test["session"].events == []


@pytest.mark.asyncio
async def test_boots_cordis_yml_and_records_feedback_without_model_visible_output(monkeypatch):
    """
    The upstream loader-composition case: the four rows are mounted through a
    real config tree, and `/feedback` then behaves identically through the
    composed registry. The Python runtime answers the rows from the installation
    table (`dsh/boot/plugin_registry.py`) instead of a stubbed Node module map,
    which is the same installation-owned resolution the Node runtime performs.
    """
    home = tempfile.mkdtemp(prefix="dsh-command-feedback-loader-")
    monkeypatch.setenv("DSH_HOME", home)
    config_path = os.path.join(home, "cordis.yml")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(
            "- name: '@deepseek-ai/dsh-agent'\n"
            "- name: '@deepseek-ai/dsh-session'\n"
            "- name: '@deepseek-ai/dsh-commands'\n"
            "- name: '@deepseek-ai/dsh-command-feedback'\n"
        )

    ctx = await boot("dsh", config_path)
    try:
        store = ctx.get("sessions")
        agent = Agent(session=store.create("feedback-loader-agent"), ctx=ctx, agent_id="feedback-loader-agent")
        registry = ctx.get("agents")
        if registry is not None and hasattr(registry, "register"):
            registry.register(agent)
        signal = AbortController().signal

        # Discoverable through the composed registry, as a UI adapter finds it.
        assert "feedback" in [descriptor.name for descriptor in ctx.commands.list(agent)]

        accepted = await ctx.commands.execute(
            agent, "/feedback the diff view is unreadable", [], signal
        )
        user_id = get_or_create_anonymous_user_id({"env": {"DSH_HOME": home}})
        assert dict(accepted.result) == {
            "kind": "success",
            "text": (
                "Feedback recorded for session feedback-loader-agent\n"
                f"Anonymous user: {user_id}. Session sharing is not configured."
            ),
        }
        rejected = await ctx.commands.execute(agent, "/feedback", [], signal)
        assert dict(rejected.result) == {
            "kind": "error",
            "text": "Feedback text is required. Usage: /feedback <text>",
        }

        # The domain event owns the payload; generic command bookkeeping omits it.
        assert [event["type"] for event in agent.session.events] == [
            "command/run",
            "feedback/record",
            "command/done",
            "command/run",
            "command/done",
        ]
        run_event = next(
            event for event in agent.session.events if event["type"] == "command/run"
        )
        assert "args" not in run_event["data"]
        feedback = next(
            event for event in agent.session.events if event["type"] == "feedback/record"
        )
        assert feedback["data"]["text"] == "the diff view is unreadable"

        # Nothing reached the model.
        assert agent.session.derive_messages() == []
        assert agent.session.surface.nodes == []
    finally:
        await ctx.fiber.dispose()
