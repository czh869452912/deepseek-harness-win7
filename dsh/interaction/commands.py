"""
Plugin-owned human-command registry shared by interactive UI adapters.
1:1 with reference/packages/interaction/commands/src/{index.ts,types.ts,brand.ts}.

The registry is a Cordis `Service` mounted at `ctx.commands`: plain-context
definitions are global, definitions registered through a command-injected child
of an agent context shadow globals for that agent (`ScopedLayers`), and every
registration is an effect of the registering context, so disposal restores the
previous view (HMR safety).

A resolved command's lifecycle is logged on the receiving session with direct
log-only appends: `command/run` before the handler is invoked and
`command/done` after settlement (a thrown or aborted handler settles as
`kind: 'error'`). Admission misses -- a line that is not a command, or a name
that does not resolve -- log nothing.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import inspect
import re
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from dsh.attachment.admission import admit_encoded_images
from dsh.attachment.error import AttachmentError
from dsh.core.abort import AbortSignal
from dsh.core.scope import NamedEntries, ScopeLayer, ScopedLayers
from dsh.core.session.json import FrozenList, deep_freeze
from dsh.cordis.service import Service

__all__ = [
    "COMMAND_NAME",
    "COMMAND_NAME_PATTERN",
    "CommandAborted",
    "CommandAbortedError",
    "CommandDefinition",
    "CommandDescriptor",
    "CommandExecution",
    "CommandInvocation",
    "CommandLayer",
    "CommandRegistry",
    "CommandRuntime",
    "CommandId",
    "CommandsPlugin",
    "abort_error",
    "abortError",
    "cancellation_of",
    "cancellationOf",
    "normalize_definition",
    "normalize_result",
    "normalizeDefinition",
    "normalizeResult",
    "parse_command",
    "parseCommand",
]

#: Plugin row name this package mounts as.
NAME = "commands"

#: The command-name grammar, used both to parse a line and to validate a
#: definition.
COMMAND_NAME_PATTERN = r"[a-z][a-z0-9_-]*"

#: The `String(/^[a-z][a-z0-9_-]*$/u)` form the definition diagnostic
#: interpolates verbatim.
COMMAND_NAME = "/^[a-z][a-z0-9_-]*$/u"

_COMMAND_NAME_RE = re.compile("^" + COMMAND_NAME_PATTERN + "$")
_LINE_RE = re.compile(r"^/(?P<name>" + COMMAND_NAME_PATTERN + r")(?=$|[\t\n\r ])")

#: Shared frozen attachments value for image-free invocations.
_NO_ATTACHMENTS = FrozenList()


def CommandId(value: str) -> str:
    """
    Brand one executor-minted pairing id.

    @param value: the pairing id string.
    @returns: the same string; no validation is performed.
    """
    return value


class CommandAborted(RuntimeError):
    """One command execution rejected by its owning UI request's signal."""

    code = "COMMAND_ABORTED"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.name = "CommandAborted"


#: The reference spelling of this package's abort failure.
CommandAbortedError = CommandAborted


def _has_field(value: Any, name: str) -> bool:
    """Whether one registration/result carries a field (JS `name in value`)."""
    if isinstance(value, Mapping):
        return name in value
    return hasattr(value, name)


def _field(value: Any, name: str) -> Any:
    """Read one field, accepting a mapping or an attribute object."""
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


class CommandDescriptor:
    """
    Handler-free immutable command view returned to UI adapters.

    The fields are read-only properties over slots, so a write raises
    `AttributeError` where a strict-mode write to a frozen object throws.
    """

    __slots__ = ("_name", "_description", "_input")

    def __init__(self, name: str, description: str, input_descriptor: Optional[Mapping[str, Any]]) -> None:
        self._name = name
        self._description = description
        self._input = input_descriptor

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input(self) -> Optional[Mapping[str, Any]]:
        return self._input

    def to_dict(self) -> Dict[str, Any]:
        """The descriptor's discovered shape, matching the reference literal."""
        view: Dict[str, Any] = {"name": self._name, "description": self._description}
        if self._input is not None:
            view["input"] = self._input
        return view

    toDict = to_dict

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, CommandDescriptor):
            return self.to_dict() == other.to_dict()
        if isinstance(other, Mapping):
            return self.to_dict() == dict(other)
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self) -> int:
        return hash((self._name, self._description))

    def __repr__(self) -> str:
        return f"<CommandDescriptor {self._name!r}>"


class CommandDefinition:
    """
    One normalized, immutable command registration.

    `record_input` is `None` when the definition omitted `recordInput`: the
    reference distinguishes "absent" from an explicit boolean only for the
    `command/run` payload shape, and both record the input.
    """

    __slots__ = ("_name", "_description", "_input", "_record_input", "_handler")

    def __init__(
        self,
        name: str,
        description: str,
        input_descriptor: Optional[Mapping[str, Any]],
        record_input: Optional[bool],
        handler: Callable[[Any], Any],
    ) -> None:
        self._name = name
        self._description = description
        self._input = input_descriptor
        self._record_input = record_input
        self._handler = handler

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input(self) -> Optional[Mapping[str, Any]]:
        return self._input

    @property
    def record_input(self) -> Optional[bool]:
        return self._record_input

    recordInput = record_input

    @property
    def handler(self) -> Callable[[Any], Any]:
        return self._handler

    def __repr__(self) -> str:
        return f"<CommandDefinition {self._name!r}>"


class RegisteredCommand:
    """One definition together with the descriptor its layer publishes."""

    __slots__ = ("definition", "descriptor")

    def __init__(self, definition: CommandDefinition, descriptor: CommandDescriptor) -> None:
        self.definition = definition
        self.descriptor = descriptor


class CommandInvocation:
    """Invocation passed to one registered command handler."""

    __slots__ = ("_command_id", "_agent", "_raw_input", "_attachments", "_signal")

    def __init__(
        self,
        command_id: str,
        agent: Any,
        raw_input: str,
        attachments: Any,
        signal: Optional[AbortSignal],
    ) -> None:
        self._command_id = command_id
        self._agent = agent
        self._raw_input = raw_input
        self._attachments = attachments
        self._signal = signal

    @property
    def command_id(self) -> str:
        return self._command_id

    commandId = command_id

    @property
    def agent(self) -> Any:
        return self._agent

    @property
    def raw_input(self) -> str:
        return self._raw_input

    rawInput = raw_input

    @property
    def attachments(self) -> Any:
        return self._attachments

    @property
    def signal(self) -> Optional[AbortSignal]:
        return self._signal

    def __repr__(self) -> str:
        return f"<CommandInvocation {self._command_id!r}>"


class CommandExecution:
    """One settled command execution: the normalized result and its pairing id."""

    __slots__ = ("_command_id", "_result")

    def __init__(self, command_id: str, result: Mapping[str, Any]) -> None:
        self._command_id = command_id
        self._result = result

    @property
    def command_id(self) -> str:
        return self._command_id

    commandId = command_id

    @property
    def result(self) -> Mapping[str, Any]:
        return self._result

    def __repr__(self) -> str:
        return f"<CommandExecution {self._command_id!r} {self._result!r}>"


class CommandLayer(ScopeLayer):
    """All command registrations owned by one global or scoped layer."""

    def __init__(self, scope: Any) -> None:
        self.scope = scope
        self.commands: NamedEntries = NamedEntries(self._duplicate_error)

    def _duplicate_error(self, name: str) -> Exception:
        if self.scope is None:
            return RuntimeError(
                f'command "{name}" is already registered (for a per-agent variant, '
                "mount a command-injected plugin under that agent's `agent.ctx`)"
            )
        return RuntimeError(f'command "{name}" is already registered in this scope')

    def is_empty(self) -> bool:
        return self.commands.is_empty()

    isEmpty = is_empty


def parse_command(line: str) -> Optional[Dict[str, str]]:
    """
    Parse an exact slash command without normalizing its trailing input.

    @param line: complete candidate command line.
    @returns: `{'name', 'rawInput'}`, or `None` when the line is not a command.
    """
    match = _LINE_RE.match(line)
    if match is None:
        return None
    return {"name": match.group("name"), "rawInput": line[match.end():]}


parseCommand = parse_command


def _render_thrown(value: Any) -> str:
    """Render arbitrary thrown values without trusting their string coercion."""
    try:
        return str(value)
    except Exception:
        return "<unrenderable thrown value>"


def _message_of(error: Any) -> str:
    """
    The failure text one thrown value contributes to `command/done`.

    Reference `settleThrown` reads `error.message` for an `Error` and renders
    anything else. The port's own failure classes carry that field
    (`AttachmentError.message`); a class without it is rendered like any other
    thrown value, contained against a failing `__str__`.
    """
    message = getattr(error, "message", None)
    if isinstance(message, str):
        return message
    return _render_thrown(error)


def abort_error(signal: Any) -> BaseException:
    """Convert arbitrary abort reasons to one stable rejected error."""
    reason = getattr(signal, "reason", None)
    if isinstance(reason, BaseException):
        return reason
    if isinstance(reason, str):
        return CommandAborted(reason)
    return CommandAborted("command aborted")


def cancellation_of(signal: Any) -> Optional[BaseException]:
    """The signal's normalized abort error when it is already aborted."""
    if signal is not None and getattr(signal, "aborted", False):
        return abort_error(signal)
    return None


def _abort_waiter(signal: Any) -> Optional[Any]:
    """
    Return an awaitable that settles when `signal` aborts, or `None` when the
    signal exposes no notification surface the port can observe.
    """
    waiter = getattr(signal, "wait_aborted", None)
    if callable(waiter):
        return waiter()
    add = getattr(signal, "add_listener", None) or getattr(signal, "addEventListener", None)
    if not callable(add):
        return None
    loop = asyncio.get_event_loop()
    future: "asyncio.Future[None]" = loop.create_future()

    def _on_abort(*_args: Any) -> None:
        if not future.done():
            future.set_result(None)

    add("abort", _on_abort)
    if getattr(signal, "aborted", False) and not future.done():
        future.set_result(None)
    return future


async def _with_abort(value: Any, signal: Any) -> Any:
    """
    Stop awaiting an uncooperative handler once its owning UI request aborts.

    The handler keeps running (the reference stops awaiting its promise, it does
    not cancel it), so a settlement that arrives after the abort is consumed
    rather than surfacing as an unretrieved failure.
    """
    if signal is None:
        if inspect.isawaitable(value):
            return await value
        return value
    if getattr(signal, "aborted", False):
        raise abort_error(signal)
    if not inspect.isawaitable(value):
        return value

    waiter_value = _abort_waiter(signal)
    if waiter_value is None:
        return await value

    task = asyncio.ensure_future(value)
    waiter = asyncio.ensure_future(waiter_value)
    try:
        done, _pending = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if not waiter.done():
            waiter.cancel()
        if not task.done():
            # Detach the handler without cancelling it; its settlement (or
            # failure) is consumed so the abandoned await stays silent.
            task.add_done_callback(_consume_settlement)
    if task in done:
        return task.result()
    raise abort_error(signal)


def _consume_settlement(settled: "asyncio.Future[Any]") -> None:
    """Retrieve a detached handler's settlement so no failure surfaces warn."""
    if settled.cancelled():
        return
    settled.exception()


def normalize_definition(definition: Any) -> RegisteredCommand:
    """
    Reject invalid command metadata before it can reach a UI protocol.

    @param definition: the `name`/`description`/`input`/`recordInput`/`handler`
        registration a caller supplies.
    @returns: the frozen definition and its discovery descriptor.
    """
    if definition is None:
        raise TypeError("command definition must be an object")

    name = _field(definition, "name")
    description = _field(definition, "description")
    handler = _field(definition, "handler")
    has_input = _has_field(definition, "input")
    raw_input = _field(definition, "input")
    record_input = _field(definition, "recordInput")
    if not _has_field(definition, "recordInput") and _has_field(definition, "record_input"):
        record_input = _field(definition, "record_input")

    if not isinstance(name, str) or _COMMAND_NAME_RE.match(name) is None:
        raise TypeError(f'command name "{name}" must match {COMMAND_NAME}')
    if not isinstance(description, str):
        raise TypeError(f'command "{name}" description must be a string')
    if len(description.strip()) == 0:
        raise TypeError(f'command "{name}" description must not be empty')
    if not callable(handler):
        raise TypeError(f'command "{name}" handler must be a function')

    normalized_input: Optional[Mapping[str, Any]] = None
    if has_input and raw_input is not None:
        if not _has_field(raw_input, "hint"):
            raise TypeError(f'command "{name}" input hint must be a string')
        hint = _field(raw_input, "hint")
        if not isinstance(hint, str):
            raise TypeError(f'command "{name}" input hint must be a string')
        if len(hint.strip()) == 0:
            raise TypeError(f'command "{name}" input hint must not be empty')
        images = _field(raw_input, "images")
        if _has_field(raw_input, "images") and not isinstance(images, bool):
            raise TypeError(f'command "{name}" input images flag must be a boolean')
        input_view: Dict[str, Any] = {"hint": hint}
        if images is True:
            input_view["images"] = True
        normalized_input = deep_freeze(input_view)
    elif has_input:
        # An explicit null (`input: null`) is not "no input" in the reference.
        raise TypeError(f'command "{name}" input hint must be a string')

    normalized = CommandDefinition(
        name=name,
        description=description,
        input_descriptor=normalized_input,
        record_input=record_input if isinstance(record_input, bool) else None,
        handler=handler,
    )
    return RegisteredCommand(
        normalized, CommandDescriptor(name, description, normalized_input)
    )


normalizeDefinition = normalize_definition


def normalize_result(command: str, value: Any) -> Mapping[str, Any]:
    """
    Validate and detach an untrusted handler result at the registry boundary.

    @param command: the command name the diagnostic interpolates.
    @param value: the handler's raw return value.
    @returns: the frozen `{'kind': 'success' | 'error', ...}` result.
    """
    if not isinstance(value, Mapping) or "kind" not in value:
        raise TypeError(f'command "{command}" handler must return a CommandResult')
    kind = value.get("kind")
    if kind == "success":
        has_text = _has_field(value, "text")
        text = value.get("text")
        if has_text and not isinstance(text, str):
            raise TypeError(f'command "{command}" success text must be a string when supplied')
        has_seq = _has_field(value, "sourceEventSeq")
        source_event_seq = value.get("sourceEventSeq")
        if has_seq and (
            not isinstance(source_event_seq, int)
            or isinstance(source_event_seq, bool)
            or source_event_seq < 0
        ):
            raise TypeError(
                f'command "{command}" success sourceEventSeq must be a non-negative safe integer when supplied'
            )
        result: Dict[str, Any] = {"kind": "success"}
        if has_text:
            result["text"] = text
        if has_seq:
            result["sourceEventSeq"] = source_event_seq
        return deep_freeze(result)
    if kind == "error":
        text = value.get("text")
        if not isinstance(text, str) or len(text.strip()) == 0:
            raise TypeError(f'command "{command}" error text must be a non-empty string')
        return deep_freeze({"kind": "error", "text": text})
    raise TypeError(
        f'command "{command}" returned unknown result kind "{_render_thrown(kind)}"'
    )


normalizeResult = normalize_result


class CommandRuntime(Service):
    """
    Human-command registry mounted at `ctx.commands`.

    Plain-context definitions are global; definitions registered through a
    command-injected child of an agent context shadow globals for that agent.
    """

    id = NAME
    name = "@deepseek-ai/dsh-commands"

    def __init__(self, ctx: Any = None, config: Any = None) -> None:
        super().__init__(ctx, NAME)
        self._layers = ScopedLayers(lambda scope: CommandLayer(scope), self._notify_change)
        self._command_seq = 0
        self._instance_token = uuid.uuid4().hex[:8]

    def apply(self, ctx: Any = None) -> None:
        """Mount as a plugin row: the service is provided by `__init__`."""
        target_ctx = ctx or self.ctx
        if target_ctx is not None and not target_ctx.has(NAME):
            target_ctx.set_service(NAME, self)

    @property
    def layers(self) -> ScopedLayers:
        return self._layers

    def register(self, definition: Any) -> Callable[[], None]:
        """
        Register a global or calling-agent-scoped command.

        @param definition: the discovery metadata and direct handler.
        @returns: the exact effect disposer that unregisters this definition.
        """
        registered = normalize_definition(definition)
        return self._layers.effect(
            self.ctx,
            lambda layer: layer.commands.insert(registered.definition.name, registered),
            {"label": "commands.register()"},
        )

    def list(self, agent: Any) -> Tuple[CommandDescriptor, ...]:
        """
        List the effective immutable command descriptors for one agent.

        @param agent: exact receiving agent and scoped-layer key.
        @returns: name-sorted descriptors after scoped shadowing.
        """
        commands = list(self._view(agent).values())
        commands.sort(key=lambda command: command.definition.name)
        return tuple(command.descriptor for command in commands)

    def find(self, agent: Any, name: str) -> Optional[CommandDefinition]:
        """
        Resolve one effective command definition.

        @param agent: exact receiving agent and scoped-layer key.
        @param name: command name without a slash.
        @returns: the scoped shadow or global definition.
        """
        command = self._view(agent).get(name)
        return command.definition if command is not None else None

    async def execute(
        self,
        agent: Any,
        line: str,
        images: Sequence[Mapping[str, Any]] = (),
        signal: Optional[AbortSignal] = None,
    ) -> Optional[CommandExecution]:
        """
        Parse and execute a known command without sending it to the model.

        A resolved command's lifecycle is logged: `command/run` is appended
        before the handler is invoked and `command/done` after settlement (a
        thrown or aborted handler settles as `kind: 'error'`). Both are direct
        log-only appends -- no turn wraps them. Admission misses (syntax or
        unknown name) log nothing. A `command/run` append failure fails the
        execution loud; a `command/done` append failure on the handler-failure
        path is contained so the handler's own error stays the reported failure.

        @param agent: exact receiving agent.
        @param line: complete slash-command line.
        @param images: base64-encoded composer images accompanying the line, in
            submission order; empty for a plain invocation.
        @param signal: cancellation signal owned by the UI request.
        @returns: the settled execution (result + lifecycle pairing id), or
            `None` when syntax or name does not resolve.
        """
        parsed = parse_command(line)
        if parsed is None:
            return None
        command = self._view(agent).get(parsed["name"])
        if command is None:
            return None
        if signal is not None and getattr(signal, "aborted", False):
            raise abort_error(signal)

        definition = command.definition
        session = getattr(agent, "session", None)
        command_id = self._mint_command_id()
        run_data: Dict[str, Any] = {"commandId": command_id, "name": parsed["name"]}
        if definition.record_input is not False:
            run_data["args"] = parsed["rawInput"]
        run_data["source"] = {"kind": "user"}
        self._append_lifecycle(session, "command/run", run_data)

        def settle(result: Mapping[str, Any]) -> CommandExecution:
            done_data: Dict[str, Any] = {"commandId": command_id, "kind": result["kind"]}
            if _has_field(result, "text"):
                done_data["text"] = result["text"]
            if result["kind"] == "success" and _has_field(result, "sourceEventSeq"):
                done_data["sourceEventSeq"] = result["sourceEventSeq"]
            self._append_lifecycle(session, "command/done", done_data)
            return CommandExecution(command_id, deep_freeze(dict(result)))

        attachments: Any = _NO_ATTACHMENTS
        if len(images) > 0:
            if definition.input is None or definition.input.get("images") is not True:
                return settle(
                    _error_result(f"/{parsed['name']} does not accept image attachments")
                )
            store = self.ctx.get("attachments") if self.ctx is not None else None
            if store is None:
                return settle(
                    _error_result(
                        f"/{parsed['name']}: image attachments are unavailable because no attachment store is composed"
                    )
                )
            try:
                refs = admit_encoded_images(store, images)
                if inspect.isawaitable(refs):
                    refs = await refs
                attachments = FrozenList(
                    [deep_freeze({"type": "image", "attachment": ref}) for ref in refs]
                )
            except AttachmentError as error:
                return settle(_error_result(_message_of(error)))
            except Exception as error:
                self._settle_thrown(session, parsed["name"], command_id, error)
                raise

            # Cancellation must be honored BEFORE the handler runs: admission
            # may await slow storage, and a handler entered after the caller
            # cancelled would mutate state the retrying caller then duplicates.
            cancelled = cancellation_of(signal)
            if cancelled is not None:
                self._settle_thrown(session, parsed["name"], command_id, cancelled)
                raise cancelled

        invocation = CommandInvocation(
            command_id, agent, parsed["rawInput"], attachments, signal
        )
        try:
            output = definition.handler(invocation)
            result = normalize_result(parsed["name"], await _with_abort(output, signal))
        except Exception as error:
            self._settle_thrown(session, parsed["name"], command_id, error)
            raise
        return settle(result)

    def _settle_thrown(
        self, session: Any, command: str, command_id: str, error: Any
    ) -> None:
        """Contained `command/done` error append for a thrown handler or admission failure."""
        try:
            self._append_lifecycle(
                session,
                "command/done",
                {"commandId": command_id, "kind": "error", "text": _message_of(error)},
            )
        except Exception as append_error:
            logger = getattr(self.ctx, "logger", None)
            if logger is not None:
                logger.warn(
                    f'command "{command}": command/done append failed: {_render_thrown(append_error)}'
                )

    def _mint_command_id(self) -> str:
        """Mint the next pairing id (monotonic; instance-token-prefixed)."""
        self._command_seq += 1
        return f"cmd-{self._instance_token}-{self._command_seq}"

    def _append_lifecycle(self, session: Any, event_type: str, data: Dict[str, Any]) -> Any:
        """
        Append one log-only lifecycle event directly: no turn is opened for it
        and no flush is forced, exactly like the reference `appendLifecycle`.
        """
        return session.append(event_type, data)

    def _view(self, agent: Any) -> Dict[str, Any]:
        """Resolve global definitions followed by exact scoped shadows."""
        return self._layers.merge(agent, lambda layer: layer.commands)

    def _notify_change(self) -> None:
        """
        Notify every registry observer without making UI refresh load-bearing.

        Registry notifications are non-vetoing, so each callback is contained
        independently: one synchronous throw cannot starve later listeners and a
        rejected listener is reported, not propagated.
        """
        ctx = self.ctx
        if ctx is None or not hasattr(ctx, "events"):
            return
        logger = getattr(ctx, "logger", None)
        for callback in ctx.events.dispatch("emit", ["commands/change"]):
            try:
                returned = callback()
            except Exception as error:
                if logger is not None:
                    logger.warn(f"commands/change listener threw: {_render_thrown(error)}")
                continue
            if inspect.isawaitable(returned):
                task = asyncio.ensure_future(returned)

                def _report(settled: "asyncio.Future[Any]", _logger: Any = logger) -> None:
                    if settled.cancelled():
                        return
                    error = settled.exception()
                    if error is not None and _logger is not None:
                        _logger.warn(
                            f"commands/change listener rejected: {_render_thrown(error)}"
                        )

                task.add_done_callback(_report)


def _error_result(text: str) -> Dict[str, Any]:
    return {"kind": "error", "text": text}


class CommandsPlugin(CommandRuntime):
    """
    Plugin row `@deepseek-ai/dsh-commands`: the plugin and the service are the
    same object, exactly like the reference default export.
    """


#: The reference default export.
default = CommandRuntime

#: Historical name this package's service has been imported as.
CommandRegistry = CommandRuntime

# CamelCase aliases for TS parity
abortError = abort_error
cancellationOf = cancellation_of
