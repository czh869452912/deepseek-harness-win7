"""
Launcher-to-application command line service and helpers matching @deepseek-ai/dsh-cmdline 1:1.
Port of reference/packages/boot/cmdline/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from dsh.cordis.context import Context


class CmdlineArgs:
    """
    Immutable argument snapshot delivered by launcher to app.
    """
    def __init__(self, args: Sequence[str]):
        self._args = tuple(args)

    def get(self) -> Tuple[str, ...]:
        return self._args


class AppReady:
    """
    Successful application-startup signal interface.
    """
    def on_ready(self, listener: Callable[[], None]) -> Callable[[], None]:
        raise NotImplementedError

    onReady = on_ready


class _Internals:
    """
    Process streams and microtask dispatch used by app command lines; tests may substitute them.
    """
    def __init__(self) -> None:
        self.stdin: Any = sys.stdin
        self.stdout: Any = sys.stdout
        self.stderr: Any = sys.stderr

    def queue_microtask(self, fn: Callable[[], None]) -> None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon(fn)
                return
        except Exception:
            pass
        fn()

    queueMicrotask = queue_microtask


internals = _Internals()


def provide_cmdline(ctx: Context, host: Any) -> None:
    """
    Provide launcher facts on a host context before any tree entry mounts:
    the command line (cmdlineArgs), bounded exit request (appExit), and optional
    successful-startup signal (appReady).
    """
    if isinstance(host, dict):
        args = host.get("args", [])
        exit_fn = host.get("exit")
        ready = host.get("ready")
    else:
        args = getattr(host, "args", [])
        exit_fn = getattr(host, "exit", None)
        ready = getattr(host, "ready", None)

    snapshot = tuple(args)
    ctx.provide("cmdlineArgs", CmdlineArgs(snapshot))
    ctx.provide("appExit", exit_fn)
    if ready is not None:
        ctx.provide("appReady", ready)


provideCmdline = provide_cmdline


def exit_on_stdin_end(ctx: Context, label: str) -> None:
    """
    Make stdin EOF request launcher bounded successful shutdown after AppReady commits.
    """
    exit_fn = ctx.get("appExit")
    ready = ctx.get("appReady")
    if exit_fn is None or ready is None:
        raise RuntimeError("stdio app: the launcher must provide ctx.appExit and ctx.appReady before the tree mounts")

    stdin = internals.stdin
    active = [True]
    ended = [False]
    cancel_ready = [lambda: None]

    def on_end() -> None:
        if not active[0] or ended[0]:
            return
        ended[0] = True
        on_ready_fn = getattr(ready, "on_ready", getattr(ready, "onReady", None))
        if callable(on_ready_fn):
            cancel_ready[0] = on_ready_fn(lambda: exit_fn(0))
        elif callable(ready):
            cancel_ready[0] = ready(lambda: exit_fn(0))

    def cleanup() -> None:
        active[0] = False
        if cancel_ready[0]:
            cancel_ready[0]()
        if hasattr(stdin, "off"):
            stdin.off("end", on_end)
        elif hasattr(stdin, "remove_listener"):
            stdin.remove_listener("end", on_end)

    ctx.effect(lambda: cleanup, label=label)

    if hasattr(stdin, "once"):
        stdin.once("end", on_end)
    elif hasattr(stdin, "on"):
        stdin.on("end", on_end)

    if getattr(stdin, "readableEnded", getattr(stdin, "readable_ended", False)):
        internals.queue_microtask(on_end)


exitOnStdinEnd = exit_on_stdin_end


class CommanderError(Exception):
    """
    Control flow exception raised by Command on help, version, or option/argument error.
    """
    def __init__(self, code: str, exit_code: int, message: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.exitCode = exit_code
        self.exit_code = exit_code
        self.message = message


class Command:
    """
    Lightweight Commander-compatible parser for application commands.
    """
    def __init__(self, name: str = "") -> None:
        self._name = name
        self._options: List[Dict[str, Any]] = []
        self._commands: List[Command] = []
        self._action_handler: Optional[Callable[..., Any]] = None
        self._parsed_opts: Dict[str, Any] = {}
        self._exit_override = False
        self._write_out: Callable[[str], Any] = lambda text: internals.stdout.write(text)
        self._write_err: Callable[[str], Any] = lambda text: internals.stderr.write(text)

    @property
    def commands(self) -> List["Command"]:
        return self._commands

    def name(self, val: Optional[str] = None) -> Any:
        if val is None:
            return self._name
        self._name = val
        return self

    def exit_override(self) -> "Command":
        self._exit_override = True
        return self

    exitOverride = exit_override

    def configure_output(self, cfg: Optional[Dict[str, Any]] = None, **kwargs: Any) -> "Command":
        c = cfg or kwargs
        if "writeOut" in c:
            self._write_out = c["writeOut"]
        elif "write_out" in c:
            self._write_out = c["write_out"]
        if "writeErr" in c:
            self._write_err = c["writeErr"]
        elif "write_err" in c:
            self._write_err = c["write_err"]
        return self

    configureOutput = configure_output

    def option(self, flags: str, description: str = "") -> "Command":
        parts = [p.strip() for p in flags.split(",")]
        long_name = None
        short_name = None
        takes_arg = False
        for part in parts:
            tokens = part.split()
            flag = tokens[0]
            if len(tokens) > 1 and (tokens[1].startswith("<") or tokens[1].startswith("[")):
                takes_arg = True
            if flag.startswith("--"):
                long_name = flag[2:]
            elif flag.startswith("-"):
                short_name = flag[1:]
        opt_name = long_name or short_name or "opt"
        self._options.append({
            "name": opt_name,
            "long": long_name,
            "short": short_name,
            "takes_arg": takes_arg,
            "description": description,
        })
        return self

    def action(self, handler: Callable[..., Any]) -> "Command":
        self._action_handler = handler
        return self

    def command(self, name: str) -> "Command":
        sub = Command(name)
        sub._exit_override = self._exit_override
        sub._write_out = self._write_out
        sub._write_err = self._write_err
        self._commands.append(sub)
        return sub

    def opts(self) -> Dict[str, Any]:
        return self._parsed_opts

    def error(self, message: str, exit_code: int = 1) -> None:
        if not message.endswith("\n"):
            message += "\n"
        self._write_err(message)
        raise CommanderError("commander.error", exit_code, message)

    def output_help(self) -> None:
        lines = [f"Usage: {self._name or 'program'} [options]"]
        if self._commands:
            lines[0] += " [command]"
        lines.append("\nOptions:")
        lines.append("  -h, --help  display help for command")
        for opt in self._options:
            flag_str = f"--{opt['long']}" if opt["long"] else f"-{opt['short']}"
            if opt["takes_arg"]:
                flag_str += f" <{opt['name']}>"
            lines.append(f"  {flag_str:<12} {opt['description']}")
        if self._commands:
            lines.append("\nCommands:")
            for cmd in self._commands:
                lines.append(f"  {cmd._name}")
        text = "\n".join(lines) + "\n"
        self._write_out(text)

    def parse(self, argv: Sequence[str], options: Optional[Dict[str, Any]] = None) -> None:
        if argv and self._commands:
            first = argv[0]
            for sub in self._commands:
                if sub._name == first:
                    sub.parse(argv[1:], options)
                    return

        if "-h" in argv or "--help" in argv:
            self.output_help()
            raise CommanderError("commander.help", 0, "help")

        idx = 0
        parsed: Dict[str, Any] = {}
        while idx < len(argv):
            arg = argv[idx]
            if arg.startswith("--"):
                key_val = arg[2:].split("=", 1)
                opt_key = key_val[0]
                matching = next((o for o in self._options if o["long"] == opt_key), None)
                if not matching:
                    self.error(f"error: unknown option '{arg}'")
                if matching["takes_arg"]:
                    if len(key_val) > 1:
                        val = key_val[1]
                    elif idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
                        idx += 1
                        val = argv[idx]
                    else:
                        self.error(f"error: option '{arg}' argument missing")
                    parsed[matching["name"]] = val
                else:
                    parsed[matching["name"]] = True
            elif arg.startswith("-") and len(arg) > 1:
                key = arg[1:]
                matching = next((o for o in self._options if o["short"] == key), None)
                if not matching:
                    self.error(f"error: unknown option '{arg}'")
                if matching["takes_arg"]:
                    if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
                        idx += 1
                        val = argv[idx]
                    else:
                        self.error(f"error: option '{arg}' argument missing")
                    parsed[matching["name"]] = val
                else:
                    parsed[matching["name"]] = True
            else:
                if self._commands:
                    matching_cmd = next((c for c in self._commands if c._name == arg), None)
                    if matching_cmd:
                        matching_cmd.parse(argv[idx + 1:], options)
                        return
                    self.error(f"error: unknown command '{arg}'")
                else:
                    pass
            idx += 1

        self._parsed_opts = parsed
        if self._action_handler is not None:
            self._action_handler()


def is_commander_error(error: Any) -> bool:
    """Return whether thrown error is a commander error."""
    if error is None:
        return False
    code = getattr(error, "code", None)
    exit_code = getattr(error, "exitCode", getattr(error, "exit_code", None))
    return isinstance(code, str) and code.startswith("commander.") and isinstance(exit_code, int)


def has_action(command: Command) -> bool:
    """Whether any command in the tree declares an action handler."""
    if getattr(command, "_action_handler", None) is not None:
        return True
    for child in getattr(command, "commands", []):
        if has_action(child):
            return True
    return False


def configure_exit_and_output(command: Command) -> None:
    """Route every command's exit and output through the launcher adapter."""
    command.exit_override()
    command.configure_output(
        write_out=lambda text: internals.stdout.write(text),
        write_err=lambda text: internals.stderr.write(text),
    )
    for child in getattr(command, "commands", []):
        configure_exit_and_output(child)


def parse_cmdline(ctx: Context, program: Command) -> None:
    """
    Parse launcher argument snapshot with an app command program.
    """
    args = ctx.get("cmdlineArgs")
    exit_fn = ctx.get("appExit")
    if args is None or exit_fn is None:
        name = program.name() if hasattr(program, "name") and callable(program.name) else "program"
        raise RuntimeError(f"{name}: the launcher must provide ctx.cmdlineArgs and ctx.appExit before the tree mounts")

    if not has_action(program):
        name = program.name() if hasattr(program, "name") and callable(program.name) else "program"
        raise RuntimeError(f"{name}: no command in the program declares an action; parseCmdline runs the invoked command's action on a successful parse, and app code there publishes its service")

    configure_exit_and_output(program)
    try:
        raw_args = list(args.get() if hasattr(args, "get") else args)
        program.parse(raw_args, {"from": "user"})
    except Exception as error:
        if is_commander_error(error):
            exit_fn(getattr(error, "exitCode", getattr(error, "exit_code", 1)))
        else:
            raise


parseCmdline = parse_cmdline
