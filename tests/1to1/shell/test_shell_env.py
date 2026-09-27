"""
1:1 parity suite for the shell environment registry
(`dsh/shell/shell_env.py`, upstream `@deepseek-ai/dsh-shell-env`).

Upstream is `reference/packages/shell/shell-env/tests/shell-env.spec.ts`:
built-in facts, contributor ownership and validation, collection ordering,
effect-scoped disposal, and the explicit disposer contract.
"""

import os
from typing import Any, Dict, List, Optional

import pytest

from dsh.cordis.context import Context
from dsh.core.tools import ToolExecutionInput
from dsh.shell.shell_env import (
    DSH_SESSION_JSONL_KEY,
    SESSION_JSONL_DESCRIPTION,
    ShellEnvPlugin,
    ShellEnvRegistry,
)

TEST_TOOL_SIGNAL = object()


class _Header:
    """Session header stand-in carrying the id the registry reads."""

    def __init__(self, session_id: str):
        self.version = 0
        self.id = session_id
        self.created_at = 0


class _Session:
    def __init__(self, session_id: str):
        self.header = _Header(session_id)


class _Agent:
    def __init__(self, session_id: str):
        self.session = _Session(session_id)


def execution(session_id: Optional[str] = None) -> ToolExecutionInput:
    """One shell tool execution, with or without a calling agent."""
    return ToolExecutionInput(
        call_id="bash-env-call",
        name="bash",
        arguments={"command": "true"},
        agent=None if session_id is None else _Agent(session_id),
        signal=TEST_TOOL_SIGNAL,
    )


class _Persistence:
    """Session-persistence stand-in exposing the `locate` seam."""

    def __init__(self, kind: str, path: str):
        self._kind = kind
        self._path = path

    def locate(self, _meta: Any) -> Dict[str, str]:
        return {"kind": self._kind, "path": self._path}


def test_collects_unconditional_shell_facts_and_the_current_agent_session_id():
    """Upstream: 'collects unconditional shell facts and the current agent session id'."""
    ctx = Context()
    registry = ShellEnvRegistry(ctx, {"dshHome": "./test-dsh-home"})

    assert registry.collect(execution()) == {
        "DSH_HOME": os.path.abspath("./test-dsh-home"),
        "DSH_SHELL": "1",
    }
    assert registry.collect(execution("session-a")) == {
        "DSH_HOME": os.path.abspath("./test-dsh-home"),
        "DSH_SESSION_ID": "session-a",
        "DSH_SHELL": "1",
    }


def test_resolves_dsh_home_from_the_ambient_override_or_the_user_home_default(monkeypatch):
    """Upstream: 'resolves DSH_HOME from the ambient override or the user-home default'."""
    monkeypatch.setenv("DSH_HOME", "./ambient-dsh-home")
    from_environment = ShellEnvRegistry(Context())
    assert from_environment.collect(execution())["DSH_HOME"] == os.path.abspath("./ambient-dsh-home")

    monkeypatch.delenv("DSH_HOME", raising=False)
    from_default = ShellEnvRegistry(Context())
    assert from_default.collect(execution())["DSH_HOME"] == os.path.join(os.path.expanduser("~"), ".dsh")


def test_collects_declared_contributor_variables_and_omits_unavailable_values():
    """Upstream: 'collects declared contributor variables and omits unavailable values'."""
    ctx = Context()
    registry = ShellEnvRegistry(ctx, {"dshHome": "./test-dsh-home"})
    registry.register({
        "name": "optional-session-fact",
        "variables": {"DSH_SESSION_OPTIONAL": {"description": "Optional session-scoped test fact."}},
        "resolve": lambda exec_: {} if exec_.agent is None else {
            "DSH_SESSION_OPTIONAL": exec_.agent.session.header.id,
        },
    })
    registry.register({
        "name": "always-available-fact",
        "variables": {"DSH_ALWAYS_AVAILABLE": {"description": "Always-available test fact."}},
        "resolve": lambda _exec: {"DSH_ALWAYS_AVAILABLE": "yes"},
    })

    assert "DSH_SESSION_OPTIONAL" not in registry.collect(execution())
    assert registry.collect(execution())["DSH_ALWAYS_AVAILABLE"] == "yes"
    assert registry.collect(execution("session-b"))["DSH_SESSION_OPTIONAL"] == "session-b"
    assert registry.list() == [
        {
            "contributor": "always-available-fact",
            "description": "Always-available test fact.",
            "key": "DSH_ALWAYS_AVAILABLE",
        },
        {
            "contributor": "optional-session-fact",
            "description": "Optional session-scoped test fact.",
            "key": "DSH_SESSION_OPTIONAL",
        },
    ]


def test_rejects_duplicate_variable_ownership_at_registration_time():
    """Upstream: 'rejects duplicate variable ownership at registration time'."""
    ctx = Context()
    registry = ShellEnvRegistry(ctx, {"dshHome": "./test-dsh-home"})
    registry.register({
        "name": "first",
        "variables": {"DSH_SHARED": {"description": "First owner."}},
        "resolve": lambda _exec: {"DSH_SHARED": "first"},
    })

    with pytest.raises(ValueError, match=r"DSH_SHARED.*first.*second"):
        registry.register({
            "name": "second",
            "variables": {"DSH_SHARED": {"description": "Second owner."}},
            "resolve": lambda _exec: {"DSH_SHARED": "second"},
        })


def test_rejects_duplicate_contributor_names_and_malformed_declarations():
    """Upstream: 'rejects duplicate contributor names and malformed declarations'."""
    registry = ShellEnvRegistry(Context(), {"dshHome": "./test-dsh-home"})
    registry.register({
        "name": "declared",
        "variables": {"DSH_DECLARED": {"description": "Declared fact."}},
        "resolve": lambda _exec: {},
    })

    with pytest.raises(ValueError, match=r"already registered"):
        registry.register({
            "name": "declared",
            "variables": {"DSH_ANOTHER": {"description": "Another fact."}},
            "resolve": lambda _exec: {},
        })
    with pytest.raises(ValueError, match=r"name must be non-empty"):
        registry.register({
            "name": " ",
            "variables": {"DSH_BLANK_NAME": {"description": "Blank owner."}},
            "resolve": lambda _exec: {},
        })
    with pytest.raises(ValueError, match=r"invalid key"):
        registry.register({
            "name": "invalid-key",
            "variables": {"dsh_invalid": {"description": "Invalid key."}},
            "resolve": lambda _exec: {},
        })
    with pytest.raises(ValueError, match=r"reserved key"):
        registry.register({
            "name": "reserved-key",
            "variables": {"DSH_HOME": {"description": "Reserved key."}},
            "resolve": lambda _exec: {},
        })
    with pytest.raises(ValueError, match=r"must describe"):
        registry.register({
            "name": "blank-description",
            "variables": {"DSH_BLANK_DESCRIPTION": {"description": " "}},
            "resolve": lambda _exec: {},
        })


def test_rejects_undeclared_variables_returned_by_a_contributor():
    """Upstream: 'rejects undeclared variables returned by a contributor'."""
    ctx = Context()
    registry = ShellEnvRegistry(ctx, {"dshHome": "./test-dsh-home"})
    registry.register({
        "name": "drifted-provider",
        "variables": {"DSH_DECLARED": {"description": "Declared fact."}},
        "resolve": lambda _exec: {"DSH_UNDECLARED": "bad"},
    })

    with pytest.raises(ValueError, match=r"drifted-provider.*DSH_UNDECLARED"):
        registry.collect(execution())


def test_rejects_non_string_values_returned_by_a_contributor():
    """Upstream: 'rejects non-string values returned by a contributor'."""
    registry = ShellEnvRegistry(Context(), {"dshHome": "./test-dsh-home"})
    registry.register({
        "name": "wrong-value-type",
        "variables": {"DSH_STRING": {"description": "String fact."}},
        "resolve": lambda _exec: {"DSH_STRING": 42},
    })

    with pytest.raises(ValueError, match=r"wrong-value-type.*non-string.*DSH_STRING"):
        registry.collect(execution())


@pytest.mark.asyncio
async def test_removes_an_effect_scoped_contributor_when_its_plugin_is_disposed():
    """Upstream: 'removes an effect-scoped contributor when its plugin is disposed'."""
    ctx = Context()
    await ctx.plugin(ShellEnvPlugin)
    registry: ShellEnvRegistry = ctx.get("shellEnv")

    from dsh.cordis.plugin import Plugin

    class TemporaryContributor(Plugin):
        inject: List[str] = ["shellEnv"]

        def apply(self, inner: Any) -> None:
            inner.get("shellEnv").register({
                "name": "temporary",
                "variables": {"DSH_TEMPORARY": {"description": "Temporary fact."}},
                "resolve": lambda _exec: {"DSH_TEMPORARY": "present"},
            })

    fiber = await ctx.plugin(TemporaryContributor)

    assert registry.collect(execution())["DSH_TEMPORARY"] == "present"
    await fiber.dispose()
    assert "DSH_TEMPORARY" not in registry.collect(execution())


def test_returns_an_explicit_contributor_disposer():
    """Upstream: 'returns an explicit contributor disposer'."""
    registry = ShellEnvRegistry(Context(), {"dshHome": "./test-dsh-home"})
    dispose = registry.register({
        "name": "explicit-disposal",
        "variables": {"DSH_EXPLICIT_DISPOSAL": {"description": "Explicitly disposed fact."}},
        "resolve": lambda _exec: {"DSH_EXPLICIT_DISPOSAL": "present"},
    })

    assert registry.collect(execution())["DSH_EXPLICIT_DISPOSAL"] == "present"
    dispose()
    assert "DSH_EXPLICIT_DISPOSAL" not in registry.collect(execution())


@pytest.mark.asyncio
async def test_the_plugin_registers_the_service_and_the_persistence_contributor_on_load():
    """Upstream: 'the plugin registers the service and the persistence contributor on load'."""
    ctx = Context()
    await ctx.plugin(ShellEnvPlugin)
    registry = ctx.get("shellEnv")
    assert isinstance(registry, ShellEnvRegistry)
    assert registry.list() == [
        {
            "contributor": "session-persistence",
            "description": SESSION_JSONL_DESCRIPTION,
            "key": DSH_SESSION_JSONL_KEY,
        },
    ]


@pytest.mark.asyncio
async def test_the_persistence_contributor_resolves_dsh_session_jsonl_only_for_a_jsonl_backend():
    """Upstream: 'the persistence contributor resolves DSH_SESSION_JSONL only for a jsonl backend'."""
    ctx = Context()
    await ctx.plugin(ShellEnvPlugin)
    ctx.provide("sessionPersistence", _Persistence("jsonl", "C:\\sessions\\s.jsonl"))
    assert ctx.get("shellEnv").collect(execution("sess-p"))[DSH_SESSION_JSONL_KEY] == "C:\\sessions\\s.jsonl"


@pytest.mark.asyncio
async def test_the_persistence_contributor_omits_the_variable_for_a_non_jsonl_backend():
    """Upstream: 'the persistence contributor omits the variable for a non-jsonl backend'."""
    ctx = Context()
    await ctx.plugin(ShellEnvPlugin)
    ctx.provide("sessionPersistence", _Persistence("sqlite", "C:\\sessions\\s.db"))
    assert DSH_SESSION_JSONL_KEY not in ctx.get("shellEnv").collect(execution("sess-p"))


@pytest.mark.asyncio
async def test_the_persistence_contributor_omits_the_variable_without_a_persistence_backend():
    """Upstream: 'the persistence contributor omits the variable without a persistence backend'."""
    ctx = Context()
    await ctx.plugin(ShellEnvPlugin)
    assert DSH_SESSION_JSONL_KEY not in ctx.get("shellEnv").collect(execution("sess-p"))
