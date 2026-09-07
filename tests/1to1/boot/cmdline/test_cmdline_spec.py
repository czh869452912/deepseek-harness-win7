"""
1:1 Parity Tests for @deepseek-ai/dsh-cmdline
Port of reference/packages/boot/cmdline/tests/cmdline.spec.ts
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import sys
import pytest
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.plugin import Plugin
from dsh.boot.cmdline import (
    Command,
    CmdlineArgs,
    AppReady,
    internals,
    provideCmdline,
    parseCmdline,
    exitOnStdinEnd,
)


class Observed:
    def __init__(self) -> None:
        self.started: Optional[Dict[str, Any]] = None
        self.exits: List[int] = []
        self.out: str = ""


class TestStdin:
    """In-memory stdin whose end edge and ended-before-bind state are controllable."""
    __test__ = False
    def __init__(self) -> None:
        self.readableEnded = False
        self.readable_ended = False
        self._listeners: Dict[str, List[Callable[..., Any]]] = {}
        self._once_listeners: Dict[str, List[Callable[..., Any]]] = {}

    def on(self, event: str, listener: Callable[..., Any]) -> "TestStdin":
        self._listeners.setdefault(event, []).append(listener)
        return self

    def once(self, event: str, listener: Callable[..., Any]) -> "TestStdin":
        self._once_listeners.setdefault(event, []).append(listener)
        return self

    def off(self, event: str, listener: Callable[..., Any]) -> "TestStdin":
        if event in self._listeners and listener in self._listeners[event]:
            self._listeners[event].remove(listener)
        if event in self._once_listeners and listener in self._once_listeners[event]:
            self._once_listeners[event].remove(listener)
        return self

    def emit(self, event: str, *args: Any) -> None:
        listeners = list(self._listeners.get(event, []))
        once_list = list(self._once_listeners.pop(event, []))
        for fn in once_list:
            fn(*args)
        for fn in listeners:
            fn(*args)

    def end(self) -> None:
        self.readableEnded = True
        self.readable_ended = True
        self.emit("end")


class PassThrough(TestStdin):
    """Buffered stream matching Node PassThrough."""
    def __init__(self) -> None:
        super().__init__()
        self.readableFlowing = False
        self._buffer: List[str] = []

    def write(self, chunk: str) -> bool:
        self._buffer.append(chunk)
        if self.readableFlowing:
            self.emit("data", chunk)
        return True

    def on(self, event: str, listener: Callable[..., Any]) -> "PassThrough":
        super().on(event, listener)
        if event == "data":
            self.readableFlowing = True
            for chunk in self._buffer:
                listener(chunk)
            self._buffer.clear()
        return self


class ReadyApp(AppReady):
    def on_ready(self, listener: Callable[[], None]) -> Callable[[], None]:
        listener()
        return lambda: None


ready_app = ReadyApp()


class ControlledAppReady(AppReady):
    def __init__(self) -> None:
        self.listeners: Set[Callable[[], None]] = set()

    def on_ready(self, listener: Callable[[], None]) -> Callable[[], None]:
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    onReady = on_ready

    def commit(self) -> None:
        for listener in list(self.listeners):
            listener()
        self.listeners.clear()


@pytest.fixture(autouse=True)
def restore_internals():
    orig_stdin = internals.stdin
    orig_stdout = internals.stdout
    orig_stderr = internals.stderr
    orig_queue = internals.queue_microtask
    yield
    internals.stdin = orig_stdin
    internals.stdout = orig_stdout
    internals.stderr = orig_stderr
    internals.queue_microtask = orig_queue


def demo_command() -> Command:
    return Command("demo").exit_override().option("--port <port>", "listen port")


def resolve_demo(program: Command) -> Dict[str, Any]:
    port = program.opts().get("port")
    if port is None:
        return {}
    if not str(port).isdigit():
        program.error(f'error: --port must be a number, got "{port}"')
    return {"port": int(port)}


async def boot_fixture(
    args: List[str],
    resolve: Callable[[Command], Any] = resolve_demo,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    opts = options or {}
    observed = Observed()

    class ObservingWriter:
        def write(self, chunk: str) -> bool:
            observed.out += chunk
            return True

    obs_writer = ObservingWriter()
    internals.stdout = obs_writer
    internals.stderr = obs_writer

    ctx = Context()
    await ctx.plugin(Loader)

    provideCmdline(ctx, {"args": args, "exit": lambda code: observed.exits.append(code)})

    class DemoStartupPlugin(Plugin):
        name = "demo-startup"
        inject = ["cmdlineArgs"]

        def apply(self, c: Context) -> None:
            program = demo_command()
            program.action(lambda: c.provide("demoStartup", resolve(program)))
            parseCmdline(c, program)

    class ReaderPlugin(Plugin):
        name = "reader"
        inject = {"demoStartup": {"required": True}} if opts.get("objectInject") else ["demoStartup"]

        def apply(self, c: Context, config: Any = None) -> None:
            observed.started = config

    if not opts.get("withoutProvider"):
        ctx.plugin(DemoStartupPlugin)

    ctx.loader.register_plugin_class("reader", ReaderPlugin)
    await ctx.loader.create({
        "name": "reader",
        "inject": {"demoStartup": {"required": True}} if opts.get("objectInject") else ["demoStartup"],
        "config": {"port": {"__jsExpr": "ctx.demoStartup.port ?? 3080"}},
    })
    await ctx.loader.wait()

    return {"observed": observed, "ctx": ctx}


# ==============================================================================
# parseCmdline tests
# ==============================================================================

@pytest.mark.asyncio
async def test_parse_cmdline_lets_row_read_flag_value_app_resolved():
    res = await boot_fixture(["--port", "8080"])
    observed = res["observed"]
    assert observed.started == {"port": 8080}
    assert observed.exits == []


@pytest.mark.asyncio
async def test_parse_cmdline_leaves_row_on_value_written_beside_expression_when_no_flag():
    res = await boot_fixture([])
    observed = res["observed"]
    assert observed.started == {"port": 3080}


@pytest.mark.asyncio
async def test_parse_cmdline_recognizes_loader_object_form_of_provider_injection():
    res = await boot_fixture(["--port", "8080"], resolve_demo, {"objectInject": True})
    observed = res["observed"]
    assert observed.started == {"port": 8080}


@pytest.mark.asyncio
async def test_parse_cmdline_prints_app_help_starts_no_reading_row_and_requests_exit_0():
    res = await boot_fixture(["--help"])
    observed = res["observed"]
    assert "Usage: demo" in observed.out
    assert observed.started is None
    assert observed.exits == [0]


@pytest.mark.asyncio
async def test_parse_cmdline_rejects_invocation_from_action_without_starting_app():
    res = await boot_fixture(["--port", "abc"])
    observed = res["observed"]
    assert "--port must be a number" in observed.out
    assert observed.started is None
    assert observed.exits == [1]


@pytest.mark.asyncio
async def test_parse_cmdline_rethrows_action_failure_that_is_not_commander_asking_to_exit():
    res = await boot_fixture([], resolve_demo, {"withoutProvider": True})
    ctx = res["ctx"]

    def bad_action():
        raise RuntimeError("action exploded")

    program = demo_command().action(bad_action)
    with pytest.raises(RuntimeError, match="action exploded"):
        parseCmdline(ctx, program)


@pytest.mark.asyncio
async def test_parse_cmdline_rethrows_thrown_value_that_is_not_an_object():
    res = await boot_fixture([], resolve_demo, {"withoutProvider": True})
    ctx = res["ctx"]

    def bad_action():
        raise Exception("action threw a string")

    program = demo_command().action(bad_action)
    with pytest.raises(Exception, match="action threw a string"):
        parseCmdline(ctx, program)


@pytest.mark.asyncio
async def test_parse_cmdline_runs_action_without_inspecting_loader_rows_or_owning_service():
    res = await boot_fixture([], resolve_demo, {"withoutProvider": True})
    ctx = res["ctx"]
    values = []
    program = demo_command()
    program.action(lambda: values.append(resolve_demo(program)))
    parseCmdline(ctx, program)
    assert values == [{}]
    assert ctx.get("demoStartup") is None


# ==============================================================================
# provideCmdline tests
# ==============================================================================

def test_provide_cmdline_hands_app_snapshot_caller_cannot_mutate():
    ctx = Context()
    args = ["--resume", "abc"]
    provideCmdline(ctx, {"args": args, "exit": lambda _: None})
    args.append("--tampered")
    cmd_args = ctx.get("cmdlineArgs")
    assert cmd_args.get() == ("--resume", "abc")


@pytest.mark.asyncio
async def test_provide_cmdline_refuses_at_load_program_in_which_no_command_declares_action():
    res = await boot_fixture([], resolve_demo, {"withoutProvider": True})
    ctx = res["ctx"]
    with pytest.raises(RuntimeError, match="no command in the program declares an action"):
        parseCmdline(ctx, demo_command())


def test_provide_cmdline_routes_preregistered_subcommand_rejection():
    ctx = Context()
    exits: List[int] = []
    err = [""]

    class ErrWriter:
        def write(self, chunk: str) -> bool:
            err[0] += chunk
            return True

    internals.stderr = ErrWriter()
    provideCmdline(ctx, {"args": ["serve"], "exit": lambda code: exits.append(code)})

    program = Command("demo")
    child = program.command("serve")
    child.action(lambda: child.error("error: serve rejected"))
    parseCmdline(ctx, program)
    assert "serve rejected" in err[0]
    assert exits == [1]


def test_provide_cmdline_fails_loud_when_parser_runs_without_launcher_values():
    ctx = Context()
    with pytest.raises(RuntimeError, match="the launcher must provide ctx.cmdlineArgs and ctx.appExit"):
        parseCmdline(ctx, demo_command())


def test_provide_cmdline_lets_multiple_parsers_read_same_snapshot():
    ctx = Context()
    provideCmdline(ctx, {"args": ["--port", "8080"], "exit": lambda _: None})

    def parse_once():
        values = []
        program = demo_command()
        program.action(lambda: values.append(resolve_demo(program)))
        parseCmdline(ctx, program)
        return values[0]

    assert parse_once() == {"port": 8080}
    assert parse_once() == {"port": 8080}
    cmd_args = ctx.get("cmdlineArgs")
    assert isinstance(cmd_args.get(), tuple)


# ==============================================================================
# exitOnStdinEnd tests
# ==============================================================================

@pytest.mark.asyncio
async def test_exit_on_stdin_end_requests_bounded_exit_on_eof_and_removes_listener():
    ctx = Context()
    stdin = TestStdin()
    exits: List[int] = []
    internals.stdin = stdin
    provideCmdline(ctx, {"args": [], "exit": lambda code: exits.append(code), "ready": ready_app})
    exitOnStdinEnd(ctx, "test.stdin")
    stdin.end()
    assert exits == [0]
    await ctx.fiber.dispose()
    stdin.emit("end")
    assert exits == [0]


@pytest.mark.asyncio
async def test_exit_on_stdin_end_requests_exit_after_binding_to_already_ended_stdin():
    ctx = Context()
    stdin = TestStdin()
    exits: List[int] = []
    stdin.readableEnded = True
    internals.stdin = stdin
    provideCmdline(ctx, {"args": [], "exit": lambda code: exits.append(code), "ready": ready_app})
    exitOnStdinEnd(ctx, "test.stdin")
    stdin.end()
    await asyncio.sleep(0.01)
    assert exits == [0]


@pytest.mark.asyncio
async def test_exit_on_stdin_end_cancels_already_ended_stream_before_queued_handler_runs():
    ctx = Context()
    stdin = TestStdin()
    exits: List[int] = []
    queued = [None]

    def mock_queue(fn):
        queued[0] = fn

    internals.queue_microtask = mock_queue
    stdin.readableEnded = True
    internals.stdin = stdin

    provideCmdline(ctx, {"args": [], "exit": lambda code: exits.append(code), "ready": ready_app})
    exitOnStdinEnd(ctx, "test.stdin")
    await ctx.fiber.dispose()
    if queued[0]:
        queued[0]()
    assert exits == []


@pytest.mark.asyncio
async def test_exit_on_stdin_end_leaves_protocol_bytes_buffered():
    ctx = Context()
    stdin = PassThrough()
    exits: List[int] = []
    internals.stdin = stdin
    provideCmdline(ctx, {"args": [], "exit": lambda code: exits.append(code), "ready": ready_app})
    exitOnStdinEnd(ctx, "test.stdin")

    frame = '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
    stdin.write(frame)
    assert stdin.readableFlowing is False

    received = [""]
    stdin.on("data", lambda chunk: received.__setitem__(0, received[0] + chunk))

    stdin.end()
    assert received[0] == frame
    assert exits == [0]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_exit_on_stdin_end_waits_for_launcher_to_commit_successful_startup():
    ctx = Context()
    stdin = TestStdin()
    exits: List[int] = []
    ready = ControlledAppReady()
    internals.stdin = stdin
    provideCmdline(ctx, {"args": [], "exit": lambda code: exits.append(code), "ready": ready})
    exitOnStdinEnd(ctx, "test.stdin")

    stdin.end()
    assert exits == []
    ready.commit()
    assert exits == [0]
    await ctx.fiber.dispose()


def test_exit_on_stdin_end_fails_loud_without_launcher_exit_request():
    internals.stdin = TestStdin()
    with pytest.raises(RuntimeError, match="launcher must provide ctx.appExit and ctx.appReady"):
        exitOnStdinEnd(Context(), "test.stdin")


def test_exit_on_stdin_end_fails_loud_without_launcher_startup_readiness():
    ctx = Context()
    internals.stdin = TestStdin()
    provideCmdline(ctx, {"args": [], "exit": lambda _: None})
    with pytest.raises(RuntimeError, match="launcher must provide ctx.appExit and ctx.appReady"):
        exitOnStdinEnd(ctx, "test.stdin")
