"""Tool registry and the Cordis tool execution pipeline."""

import asyncio
import inspect
import json
import math
from typing import Any, Callable, Dict, List, Optional, Union

from dsh.cordis.plugin import Plugin
from dsh.cordis.utils import Tracker
from dsh.llm.error import HarnessError


TOOL_ABORTED = "ABORTED"
TOOL_ABORTED_BEFORE_DISPATCH = "ABORTED_BEFORE_DISPATCH"
TOOL_RUNTIME_SCHEDULER = "TOOL_RUNTIME_SCHEDULER"
TOOL_NOT_FOUND = "UNKNOWN_TOOL"
TOOL_ARGS_INVALID = "INVALID_ARGS"
_MISSING_SIGNAL = object()
RUN_CODE_NAME = "run_code"


class ToolNotFoundError(HarnessError):
    def __init__(self, tool_name: str, reachable_from: Optional[str] = None):
        message = ('unknown tool "%s"' % tool_name if reachable_from is None
                   else 'unknown tool "%s": %s' % (tool_name, reachable_from))
        super().__init__(message, TOOL_NOT_FOUND)


class ToolArgsError(HarnessError):
    def __init__(self, tool_name: str, violations: List[str]):
        self.violations = violations
        super().__init__('tool "%s" received invalid arguments: %s' %
                         (tool_name, "; ".join(violations)), TOOL_ARGS_INVALID)


class ToolOutputError(HarnessError):
    def __init__(self, tool_name: str, violations: List[str]):
        self.violations = violations
        super().__init__('tool "%s" returned invalid output: %s' %
                         (tool_name, "; ".join(violations)), "INVALID_TOOL_OUTPUT")


class CodeRunFailedError(HarnessError):
    def __init__(self, message: str):
        super().__init__(message, "CODE_RUN_FAILED")


def _schema_violations(value: Any, schema: Any, path: str = "value") -> List[str]:
    root: List[str] = []
    tasks: List[Any] = [("node", value, schema, path, root)]
    while tasks:
        task = tasks.pop()
        if task[0] == "oneof":
            _, node_path, branches, target = task
            matches = sum(1 for branch_result in branches if not branch_result)
            if matches != 1:
                target.append('"%s" must match exactly one oneOf branch (matched %d)' %
                              (node_path, matches))
            continue
        _, candidate, node, node_path, target = task
        if type(node) not in (dict, FrozenDict) or not node:
            continue
        one_of = node.get("oneOf")
        if type(one_of) in (list, FrozenList):
            branch_results = [[] for _branch in one_of]
            tasks.append(("oneof", node_path, branch_results, target))
            for index in range(len(one_of) - 1, -1, -1):
                tasks.append(("node", candidate, one_of[index], node_path,
                              branch_results[index]))
            continue
        expected = node.get("type")
        type_matches = {
            "object": type(candidate) in (dict, FrozenDict),
            "array": type(candidate) in (list, FrozenList),
            "string": type(candidate) is str,
            "boolean": type(candidate) is bool,
            "number": type(candidate) in (int, float) and type(candidate) is not bool,
            "integer": type(candidate) is int and type(candidate) is not bool,
            "null": candidate is None,
        }
        if expected in type_matches and not type_matches[expected]:
            target.append('"%s" must be a %s' % (node_path, expected))
            continue
        if "const" in node and candidate != node["const"]:
            target.append('"%s" must equal the declared constant' % node_path)
        if "enum" in node and candidate not in node["enum"]:
            target.append('"%s" must be one of the declared values' % node_path)
        if expected == "object" and type(candidate) in (dict, FrozenDict):
            properties = node.get("properties", {})
            for name in node.get("required", []):
                if name not in candidate:
                    target.append('"%s.%s" is required' % (node_path, name))
            if type(properties) in (dict, FrozenDict):
                if node.get("additionalProperties") is False:
                    for name in candidate:
                        if name not in properties:
                            target.append('"%s.%s" is not a declared property (additionalProperties: false)' % (node_path, name))
                entries = [(name, child) for name, child in properties.items()
                           if name in candidate]
                for name, child in reversed(entries):
                    tasks.append(("node", candidate[name], child,
                                  "%s.%s" % (node_path, name), target))
        elif expected == "array" and type(candidate) in (list, FrozenList):
            items = node.get("items")
            if type(items) in (dict, FrozenDict):
                for index in range(len(candidate) - 1, -1, -1):
                    tasks.append(("node", candidate[index], items,
                                  "%s[%d]" % (node_path, index), target))
    return root


def _json_snapshot(value: Any) -> Any:
    holder: List[Any] = [None]
    active = set()
    tasks: List[Any] = [("visit", value, holder, 0)]
    while tasks:
        task = tasks.pop()
        if task[0] == "leave":
            active.remove(task[1])
            continue
        _, candidate, parent, key = task
        candidate_type = type(candidate)
        if candidate is None or candidate_type in (str, bool, int):
            parent[key] = candidate
            continue
        if candidate_type is float:
            if (not math.isfinite(candidate)
                    or (candidate == 0.0 and math.copysign(1.0, candidate) < 0)):
                raise TypeError("value must be losslessly JSON-serializable")
            parent[key] = candidate
            continue
        if candidate_type not in (dict, list, FrozenDict, FrozenList):
            raise TypeError("value must be losslessly JSON-serializable")
        identity = id(candidate)
        if identity in active:
            raise TypeError("value must be losslessly JSON-serializable")
        active.add(identity)
        tasks.append(("leave", identity))
        if candidate_type in (dict, FrozenDict):
            clone: Any = {}
            parent[key] = clone
            entries = list(candidate.items())
            for child_key, child in entries:
                if type(child_key) is not str:
                    raise TypeError("value must be losslessly JSON-serializable")
            for child_key, child in reversed(entries):
                tasks.append(("visit", child, clone, child_key))
        else:
            clone = [None] * len(candidate)
            parent[key] = clone
            for index in range(len(candidate) - 1, -1, -1):
                tasks.append(("visit", candidate[index], clone, index))
    return holder[0]


def _assert_supported_schema(schema: Any, path: str = "schema") -> None:
    allowed = {"type", "oneOf", "properties", "required", "additionalProperties",
               "items", "enum", "const", "description", "title", "default", "examples"}
    tasks = [(schema, path)]
    while tasks:
        node, node_path = tasks.pop()
        if type(node) is not dict:
            raise TypeError("%s must be a schema object" % node_path)
        unknown = [key for key in node if key not in allowed]
        if unknown:
            raise TypeError("%s.%s is not a supported keyword" % (node_path, unknown[0]))
        for annotation in ("title", "description"):
            if annotation in node and type(node[annotation]) is not str:
                raise TypeError("%s.%s must be a string" % (node_path, annotation))
        if "oneOf" in node:
            branches = node["oneOf"]
            if type(branches) is not list or len(branches) < 2:
                raise TypeError("%s.oneOf must contain at least two schemas" % node_path)
            siblings = ("type", "properties", "required", "additionalProperties",
                        "items", "enum", "const")
            if any(key in node for key in siblings):
                raise TypeError("%s.oneOf cannot have validation siblings" % node_path)
            for index in range(len(branches) - 1, -1, -1):
                tasks.append((branches[index], "%s.oneOf[%d]" % (node_path, index)))
        schema_type = node.get("type")
        if schema_type is not None and schema_type not in (
                "object", "array", "string", "number", "integer", "boolean", "null"):
            raise TypeError("%s.type is unsupported" % node_path)
        if "additionalProperties" in node and (
                schema_type != "object" or type(node["additionalProperties"]) is not bool):
            raise TypeError("%s.additionalProperties must be a boolean on an object schema" % node_path)
        properties = node.get("properties")
        if properties is not None:
            if schema_type != "object" or type(properties) is not dict:
                raise TypeError("%s.properties must be an object of schemas" % node_path)
            for name, child in reversed(list(properties.items())):
                if type(name) is not str:
                    raise TypeError("%s.properties keys must be strings" % node_path)
                tasks.append((child, "%s.properties.%s" % (node_path, name)))
        if "required" in node:
            required = node["required"]
            if schema_type != "object" or type(required) is not list or any(
                    type(name) is not str for name in required):
                raise TypeError("%s.required must be an array of property names" % node_path)
            declared = properties if type(properties) is dict else {}
            if any(name not in declared for name in required):
                raise TypeError("%s.required names must be declared in properties" % node_path)
        if "items" in node:
            if schema_type != "array":
                raise TypeError("%s.items requires type array" % node_path)
            tasks.append((node["items"], "%s.items" % node_path))
        if "enum" in node:
            values = node["enum"]
            if schema_type in (None, "object", "array") or type(values) is not list or not values:
                raise TypeError("%s.enum must be a non-empty scalar enum" % node_path)
            if any(_schema_violations(value, {"type": schema_type}, node_path) for value in values):
                raise TypeError("%s.enum values must match the schema type" % node_path)
        if "const" in node:
            if schema_type in (None, "object", "array"):
                raise TypeError("%s.const requires a scalar type" % node_path)
            if _schema_violations(node["const"], {"type": schema_type}, node_path):
                raise TypeError("%s.const must match the schema type" % node_path)
            if "enum" in node and node["const"] not in node["enum"]:
                raise TypeError("%s.const must be present in enum" % node_path)
    _json_snapshot(schema)


class FrozenDict(dict):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen dictionary")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


class FrozenList(list):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen list")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def _deep_freeze(value: Any) -> Any:
    holder: List[Any] = [None]
    tasks: List[Any] = [("visit", value, holder, 0)]
    while tasks:
        task = tasks.pop()
        if task[0] == "freeze":
            _, parent, key, mutable, kind = task
            parent[key] = FrozenDict(mutable) if kind == "dict" else FrozenList(mutable)
            continue
        _, candidate, parent, key = task
        if type(candidate) in (dict, FrozenDict):
            mutable: Any = {}
            parent[key] = mutable
            tasks.append(("freeze", parent, key, mutable, "dict"))
            for child_key, child in reversed(list(candidate.items())):
                tasks.append(("visit", child, mutable, child_key))
        elif type(candidate) in (list, FrozenList):
            mutable = [None] * len(candidate)
            parent[key] = mutable
            tasks.append(("freeze", parent, key, mutable, "list"))
            for index in range(len(candidate) - 1, -1, -1):
                tasks.append(("visit", candidate[index], mutable, index))
        else:
            parent[key] = candidate
    return holder[0]


class _FusedSignal:
    def __init__(self, caller: Any, wrapper: Any):
        self._caller = caller
        self._wrapper = wrapper

    def is_set(self) -> bool:
        return ToolsService._is_aborted(self._caller) or ToolsService._is_aborted(self._wrapper)

    @property
    def aborted(self) -> bool:
        return self.is_set()


class _ToolLayer:
    def __init__(self) -> None:
        self.tools: Dict[str, "Tool"] = {}
        self.restrictions: List[Dict[str, Any]] = []
        self.guards: List[Callable[[Any], Optional[str]]] = []
        self.mode: Optional[str] = None

    def admits(self, name: str) -> bool:
        for restriction in self.restrictions:
            allow = restriction.get("allow")
            deny = restriction.get("deny")
            if allow is not None and name not in allow:
                return False
            if deny is not None and name in deny:
                return False
        return True


class Tool:
    """A registered tool definition with legacy and canonical-output support."""

    def __init__(self, name: str, description: str, parameters: Dict[str, Any],
                 handler: Callable[..., Any], execution_mode: str = "parallel",
                 present_call: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 present_result: Optional[Callable[..., Any]] = None,
                 output: Optional[Dict[str, Any]] = None,
                 finalize_content: Optional[Callable[..., Any]] = None,
                 timeout_ms: Optional[float] = None,
                 concurrency_classifier: Optional[Callable[[Any], Any]] = None,
                 canonical: bool = False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.execution_mode = execution_mode if execution_mode in ("parallel", "exclusive") else "parallel"
        self._present_call = present_call
        self._present_result = present_result
        self.output = output
        self.finalize_content = finalize_content
        self.timeout_ms = timeout_ms
        self.concurrency_classifier = concurrency_classifier
        self.canonical = canonical

    def to_schema(self) -> Dict[str, Any]:
        return {"type": "function", "function": self.schema()}

    def schema(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "parameters": _json_snapshot(self.parameters)}

    def validate_arguments(self, args: Any) -> List[str]:
        return _schema_violations(args, self.parameters, "arguments")

    def present_call(self, args: Any) -> Any:
        if self._present_call is None or self.validate_arguments(args):
            return None
        try:
            return _json_snapshot(self._present_call(args))
        except Exception:
            return None

    def present_result(self, args: Any, result: Any) -> Any:
        if self._present_result is None or self.validate_arguments(args):
            return None
        try:
            return _json_snapshot(self._present_result(args, result))
        except Exception:
            return None

    async def execute(self, args: Dict[str, Any],
                      run_context: Optional["ToolRunContext"] = None,
                      ctx: Any = None) -> Any:
        if self.canonical:
            violations = self.validate_arguments(args)
            if violations:
                raise ToolArgsError(self.name, violations)
            result = self.handler(args, run_context)
            return await result if inspect.isawaitable(result) else result
        signature = inspect.signature(self.handler)
        kwargs = dict(args)
        if "exec" in signature.parameters and run_context is not None:
            kwargs["exec"] = run_context
        if "ctx" in signature.parameters:
            kwargs["ctx"] = ctx
        result = self.handler(**kwargs)
        return await result if inspect.isawaitable(result) else result


class ToolExecutionInput:
    """Caller-owned fields for one tool invocation."""

    def __init__(self, call_id: str, name: str, arguments: Any,
                 agent: Optional[Any] = None, signal: Any = _MISSING_SIGNAL,
                 session: Optional[Any] = None, root_call_id: Optional[str] = None,
                 parent: Optional[Any] = None,
                 metadata: Optional[Dict[str, Any]] = None, **kwargs: Any):
        self.call_id = call_id
        self.callId = call_id
        self.name = name
        self.arguments = arguments
        self.agent = agent
        self.session = session if session is not None else getattr(agent, "session", None)
        if signal is _MISSING_SIGNAL:
            raise TypeError("ToolExecutionInput signal is required and caller-owned")
        # ``None`` is accepted only for the legacy loop adapter, whose public
        # signature predates required cancellation.
        self.signal = signal if signal is not None else asyncio.Event()
        self.root_call_id = root_call_id or kwargs.get("rootCallId")
        self.rootCallId = self.root_call_id
        self.parent = parent
        self.metadata = dict(metadata or kwargs.get("call_metadata") or {})


class ToolRunContext(ToolExecutionInput):
    """Registry-owned execution identity passed to every modern handler."""

    def __init__(self, source: ToolExecutionInput):
        object.__setattr__(self, "_sealed", False)
        super().__init__(source.call_id, source.name, _deep_freeze(_json_snapshot(source.arguments)),
                         agent=source.agent, signal=source.signal, session=source.session,
                         root_call_id=source.root_call_id or source.call_id,
                         parent=source.parent, metadata=source.metadata)
        self.token = object()
        self._additional_contexts: List[Any] = []
        self._concludes_turn = False
        self._prepared_kind = "dispatch"
        self._prepared_result: Optional[ToolExecutionResult] = None
        self._caller_signal = source.signal
        self._body_invoked = False
        self._approval_cancelled = False
        self._finalizer: Optional[Callable[..., Any]] = None
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False) and not name.startswith("_") and name != "signal":
            raise AttributeError("tool execution identity is readonly")
        object.__setattr__(self, name, value)

    def defer_context(self, context: Any) -> None:
        self._additional_contexts.append(context)

    def deferContext(self, context: Any) -> None:
        self.defer_context(context)

    def conclude_turn(self) -> None:
        self._concludes_turn = True

    def concludeTurn(self) -> None:
        self.conclude_turn()


class ToolExecutionResult:
    """Normalized execution-local result."""

    def __init__(self, content: List[Dict[str, Any]], is_error: bool = False,
                 error: Optional[Dict[str, Any]] = None,
                 meta: Optional[Dict[str, Any]] = None,
                 concludes_turn: bool = False,
                 additional_contexts: Optional[List[Any]] = None,
                 value: Any = None):
        object.__setattr__(self, "_frozen", False)
        self.content = content
        self.is_error = is_error
        self.error = error
        self.meta = meta
        self.concludes_turn = concludes_turn
        self.additional_contexts = additional_contexts or []
        self.value = value

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("tool execution result is readonly")
        object.__setattr__(self, name, value)

    def freeze(self) -> "ToolExecutionResult":
        if self._frozen:
            return self
        self.content = _deep_freeze(self.content)
        if self.error is not None:
            self.error = _deep_freeze(self.error)
        if self.meta is not None:
            self.meta = _deep_freeze(self.meta)
        self.additional_contexts = _deep_freeze(self.additional_contexts)
        self.value = _deep_freeze(self.value)
        object.__setattr__(self, "_frozen", True)
        return self

    @property
    def isError(self) -> bool:
        return self.is_error

    @classmethod
    def from_raw(cls, raw: Any, is_error: bool = False,
                 error_info: Optional[Dict[str, Any]] = None) -> "ToolExecutionResult":
        if isinstance(raw, ToolExecutionResult):
            return raw
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, (dict, list)):
            text = json.dumps(raw, ensure_ascii=False, indent=2)
        else:
            text = str(raw)
        return cls([{"type": "text", "text": text}], is_error=is_error,
                   error=error_info, value=None if is_error else raw)


def _error_message(error: BaseException) -> str:
    message = getattr(error, "message", None)
    return message if isinstance(message, str) else str(error)


def _error_result(error: BaseException) -> ToolExecutionResult:
    message = _error_message(error)
    failure: Dict[str, Any] = {"message": message}
    code = getattr(error, "code", None)
    if isinstance(code, str):
        info = {"name": getattr(error, "name", error.__class__.__name__), "code": code}
        failure.update({"info": info, "name": info["name"], "code": code})
    return ToolExecutionResult([{"type": "text", "text": "Error: %s" % message}],
                               is_error=True, error=failure)


def _decision_contexts(decision: Dict[str, Any]) -> List[Any]:
    return list(decision.get("additionalContexts", decision.get("additional_contexts", [])) or [])


class ToolsService:
    """Core catalog plus pre/around/post execution orchestration."""

    def __init__(self, ctx: Any, config: Optional[Dict[str, Any]] = None):
        self.ctx = ctx
        self._tools: Dict[str, Tool] = {}
        self._cordis_tracker = Tracker(property_name="ctx")
        self._global_layer = _ToolLayer()
        self._global_layer.tools = self._tools
        self._scoped_layers: Dict[Any, _ToolLayer] = {}
        self._code_transport: Optional[Tool] = None
        config = config or {}
        self.mode = config.get("mode", "native")
        if self.mode not in ("native", "code", "both"):
            raise ValueError("tools mode must be native, code, or both")
        self.max_parallel_sub_calls = config.get("maxParallelSubCalls", 10)
        if (not isinstance(self.max_parallel_sub_calls, int)
                or isinstance(self.max_parallel_sub_calls, bool)
                or self.max_parallel_sub_calls <= 0):
            raise ValueError("maxParallelSubCalls must be a positive integer")
        self._mount_prompt_surface()

    def _mount_prompt_surface(self) -> None:
        system_prompt = self._optional_service("systemPrompt")
        if system_prompt is None:
            return
        if hasattr(system_prompt, "tools"):
            system_prompt.tools(lambda context: self.schemas(
                self._prompt_scope(context)))
        if self.mode != "native":
            self._mount_code_prompt_sections(system_prompt)

    @staticmethod
    def _prompt_scope(context: Any) -> Any:
        if type(context) is dict:
            return context.get("scope")
        return getattr(context, "scope", None)

    def _collapse_section(self) -> Dict[str, Any]:
        return {
            "name": "tools:code-only", "order": 90,
            "text": lambda context: (
                "`run_code` is the only tool you can call directly. Reach every "
                "tool declared by the SDK from inside the program."
                if self._mode_for(self._prompt_scope(context)) == "code" else ""),
        }

    def _sdk_section(self) -> Dict[str, Any]:
        return {
            "name": "tools:sdk", "order": 150,
            "text": lambda context: self.sdk_text(self._prompt_scope(context)),
        }

    def _mount_code_prompt_sections(self, system_prompt: Any) -> List[Callable[[], None]]:
        if system_prompt is None or not hasattr(system_prompt, "section"):
            return []
        disposers = []
        for section in (self._collapse_section(), self._sdk_section()):
            disposer = system_prompt.section(section)
            if callable(disposer):
                disposers.append(disposer)
        return disposers

    @staticmethod
    def _scope_context(scope: Any) -> Any:
        # Traceable service proxies carry the exact caller Context.  That
        # context is the registration owner; walking its Fiber parents here
        # incorrectly promoted plugin registrations to the root catalog.
        # Parent visibility is handled separately by _scope_chain().
        if "_parent" in getattr(scope, "__dict__", {}):
            return scope
        return getattr(scope, "ctx", scope)

    @staticmethod
    def _is_global_context(ctx: Any) -> bool:
        return ctx is None or getattr(ctx, "_parent", None) is None

    def _current_scope_context(self) -> Any:
        current = self._scope_context(self.ctx)
        return None if self._is_global_context(current) else current

    def _scope_chain(self, scope: Any) -> List[Any]:
        current = self._scope_context(scope)
        chain = []
        while current is not None and not self._is_global_context(current):
            chain.append(current)
            current = getattr(current, "_parent", None)
        chain.reverse()
        return chain

    def _layer_for(self, scope_ctx: Any, create: bool = False) -> Optional[_ToolLayer]:
        if scope_ctx is None:
            return self._global_layer
        layer = self._scoped_layers.get(scope_ctx)
        if layer is None and create:
            layer = _ToolLayer()
            self._scoped_layers[scope_ctx] = layer
        return layer

    def _view(self, scope: Any = None) -> Dict[str, Any]:
        chain = self._scope_chain(scope)
        own_ctx = chain[-1] if chain else None
        own = self._layer_for(own_ctx)
        inherited: Dict[str, Tool] = dict(self._global_layer.tools)
        layers = []
        for scope_ctx in chain:
            layer = self._layer_for(scope_ctx)
            if layer is None:
                continue
            layers.append(layer)
            if layer is own:
                continue
            inherited.update(layer.tools)
        visible: Dict[str, Tool] = {}
        known = set()
        restrictable = set()
        for name, tool in inherited.items():
            known.add(name)
            restrictable.add(name)
            if all(layer.admits(name) for layer in layers):
                visible[name] = tool
        if own is not None:
            for name, tool in own.tools.items():
                known.add(name)
                visible[name] = tool
        if self._mode_for(scope) != "native":
            visible[RUN_CODE_NAME] = self._require_code_transport()
        return {"visible": visible, "known": known, "restrictable": restrictable}

    def _mode_for(self, scope: Any = None) -> str:
        mode = self.mode
        for scope_ctx in self._scope_chain(scope):
            layer = self._layer_for(scope_ctx)
            if layer is not None and layer.mode is not None:
                mode = layer.mode
        return mode

    def _register_owned_cleanup(self, owner_ctx: Any, cleanup: Callable[[], None], label: str) -> None:
        if owner_ctx is not None and hasattr(owner_ctx, "effect"):
            owner_ctx.effect(lambda: cleanup, label=label)

    def _optional_service(self, name: str) -> Any:
        has_service = getattr(self.ctx, "has", None)
        if callable(has_service) and not has_service(name):
            return None
        getter = getattr(self.ctx, "get")
        try:
            return getter(name)
        except KeyError:
            if callable(has_service):
                raise
            return None

    def _require_code_runtime(self, mode: Optional[str] = None) -> Any:
        effective = mode or self.mode
        runtime = self._optional_service("codeRuntime")
        if runtime is None:
            raise RuntimeError(
                'dsh-tools: mode "%s" requires a code runtime - load a ctx.codeRuntime implementation or set tools mode to "native"' % effective)
        language = getattr(runtime, "language", None)
        if language not in ("python", "typescript"):
            raise RuntimeError(
                'dsh-tools: no SDK renderer registered for runtime language %r (known: "typescript", "python")' % language)
        return runtime

    def _peek_code_runtime(self) -> Any:
        return self._optional_service("codeRuntime")

    def _require_code_transport(self) -> Tool:
        language = getattr(self._peek_code_runtime(), "language", "typescript")
        if language == "python":
            description = (
                "Execute a Python program against the available tools. Takes two required "
                "arguments: `code`, the BODY of an async function (top-level `await` and "
                "`return` work), and `description`, a short summary of what the program does.")
            code_description = "The program: the body of an async Python function."
        elif language == "typescript":
            description = (
                "Execute a TypeScript program against the available tools. Takes two required "
                "arguments: `code`, the BODY of an async function (erasable syntax only; "
                "top-level `await` and `return` work), and `description`, a short summary.")
            code_description = "The program: the body of an async TypeScript function."
        else:
            raise RuntimeError(
                'dsh-tools: no run_code schema flavor registered for runtime language %r '
                '(known: "typescript", "python")' % language)
        parameters = {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": code_description},
                "description": {
                    "type": "string",
                    "description": "Clear, concise description of what this program does.",
                },
            },
            "required": ["code", "description"],
            "additionalProperties": False,
        }
        if self._code_transport is not None:
            self._code_transport.description = description
            self._code_transport.parameters = parameters
            return self._code_transport
        output = {
            "schema": {
                "type": "object",
                "properties": {
                    "logs": {"type": "array", "items": {"type": "string"}},
                    "result": {},
                },
                "required": ["logs"],
                "additionalProperties": False,
            },
            "render": self._render_run_code,
        }
        self._code_transport = Tool(
            RUN_CODE_NAME,
            description,
            parameters, self._execute_run_code, execution_mode="exclusive",
            present_call=lambda args: {
                "card": "generic", "title": args["description"],
                "kind": "execute", "rawInput": args["code"]},
            output=output, canonical=True)
        return self._code_transport

    @staticmethod
    def _render_run_code(_args: Any, value: Dict[str, Any]) -> List[Dict[str, str]]:
        parts = []
        logs = value.get("logs", [])
        if logs:
            parts.append("\n".join(logs))
        if "result" in value:
            result = value["result"]
            parts.append(result if isinstance(result, str) else json.dumps(
                result, ensure_ascii=False, indent=2))
        return [{"type": "text", "text": "\n".join(parts) if parts else
                 "(run_code completed with no output)"}]

    async def _execute_run_code(self, args: Dict[str, Any],
                                exec_input: ToolRunContext) -> Dict[str, Any]:
        if not args["description"].strip():
            raise ValueError("invalid description: expected a non-empty string")
        runtime = self._require_code_runtime(self._mode_for(exec_input.agent))
        functions: Dict[str, Callable[..., Any]] = {}
        condition = asyncio.Condition()
        waiting: List[Dict[str, Any]] = []
        active = 0
        exclusive_active = False
        dispatches = 0

        async def acquire(kind: str) -> None:
            nonlocal active, exclusive_active
            ticket = {"kind": kind}
            async with condition:
                waiting.append(ticket)
                while True:
                    position = waiting.index(ticket)
                    exclusive_ahead = any(
                        item["kind"] == "exclusive" for item in waiting[:position])
                    if kind == "exclusive":
                        ready = position == 0 and active == 0
                    else:
                        ready = (not exclusive_active and not exclusive_ahead
                                 and active < self.max_parallel_sub_calls)
                    if ready:
                        waiting.remove(ticket)
                        active += 1
                        if kind == "exclusive":
                            exclusive_active = True
                        return
                    await condition.wait()

        async def release(kind: str) -> None:
            nonlocal active, exclusive_active
            async with condition:
                active -= 1
                if kind == "exclusive":
                    exclusive_active = False
                condition.notify_all()

        async def append_session(name: str, data: Dict[str, Any]) -> None:
            session = exec_input.session
            if session is None or not hasattr(session, "append"):
                return
            returned = session.append(name, data)
            if inspect.isawaitable(returned):
                await returned

        async def shape_dispatch_log(dispatch: Dict[str, Any]) -> Any:
            try:
                return await self._carrier(exec_input).waterfall(
                    "tools/code-dispatch-log", dispatch,
                    lambda *_args: dispatch["content"])
            except Exception as error:
                logger = self._optional_service("logger")
                if logger is not None and hasattr(logger, "warn"):
                    logger.warn(
                        "tools: code-dispatch-log listener failed for %s: %s; "
                        "logging the original settled content" %
                        (dispatch["name"], _error_message(error)))
                return dispatch["content"]

        for schema in self._sdk_schemas(exec_input.agent):
            name = schema["name"]

            async def binding(raw_args: Any, tool_name: str = name) -> Any:
                nonlocal dispatches
                normalized = _json_snapshot(raw_args)
                logged_arguments = _json_snapshot(normalized)
                dispatches += 1
                sub_call_id = "%s:code:%d" % (exec_input.call_id, dispatches)
                nested_input = ToolExecutionInput(
                    sub_call_id, tool_name, normalized, agent=exec_input.agent,
                    signal=exec_input.signal, root_call_id=exec_input.root_call_id,
                    parent=exec_input.token)
                kind = self.execution_mode(nested_input)["kind"]
                await acquire(kind)
                try:
                    await append_session("tool/code-dispatch-start", {
                        "rootCallId": exec_input.root_call_id,
                        "parentCallId": exec_input.call_id,
                        "subCallId": sub_call_id,
                        "name": tool_name,
                        "arguments": logged_arguments,
                    })
                    result = await self.execute(nested_input)
                    dispatch = {
                        "exec": exec_input,
                        "agent": exec_input.agent,
                        "subCallId": sub_call_id,
                        "name": tool_name,
                        "isError": result.is_error,
                        "content": result.content,
                    }
                    logged_content = await shape_dispatch_log(dispatch)
                    await append_session("tool/code-dispatch", {
                        "rootCallId": exec_input.root_call_id,
                        "parentCallId": exec_input.call_id,
                        "subCallId": sub_call_id,
                        "name": tool_name,
                        "arguments": logged_arguments,
                        "isError": result.is_error,
                        "content": _json_snapshot(logged_content),
                    })
                finally:
                    await release(kind)
                for context in result.additional_contexts:
                    exec_input.defer_context(context)
                if result.concludes_turn:
                    exec_input.conclude_turn()
                if result.is_error:
                    raise RuntimeError(result.error.get("message", "tool call failed"))
                return _json_snapshot(result.value)

            functions[name] = binding

        request = {
            "program": args["code"],
            "bindings": [{
                "global": "tools", "functions": functions,
                "errorClass": {"name": "ToolCallError",
                               "memberNameProperty": "toolName"},
            }],
            "signal": exec_input.signal,
        }
        returned = runtime.run(request)
        run_result = await returned if inspect.isawaitable(returned) else returned
        if not isinstance(run_result, dict):
            run_result = {
                "logs": getattr(run_result, "logs", []),
                "value": getattr(run_result, "value", None),
                "error": getattr(run_result, "error", None),
            }
        error = run_result.get("error")
        if error:
            kind = error.get("kind", "runtime") if isinstance(error, dict) else getattr(error, "kind", "runtime")
            message = error.get("message", str(error)) if isinstance(error, dict) else getattr(error, "message", str(error))
            logs = list(run_result.get("logs", []))
            suffix = "\nCaptured output:\n%s" % "\n".join(logs) if logs else ""
            raise CodeRunFailedError("code run failed (%s): %s%s" % (kind, message, suffix))
        output = {"logs": _json_snapshot(list(run_result.get("logs", [])))}
        if "value" in run_result and run_result["value"] is not None:
            output["result"] = _json_snapshot(run_result["value"])
        return output

    def _sdk_schemas(self, scope: Any = None) -> List[Dict[str, Any]]:
        schemas = []
        for tool in self._view(scope)["visible"].values():
            if tool.name == RUN_CODE_NAME:
                continue
            schemas.append({"name": tool.name, "description": tool.description,
                            "parameters": _json_snapshot(tool.parameters),
                            "output": _json_snapshot(tool.output["schema"] if tool.output else {})})
        return schemas

    def sdk_text(self, scope: Any = None) -> str:
        mode = self._mode_for(scope)
        if mode == "native":
            return ""
        runtime = self._require_code_runtime(mode)
        schemas = sorted(self._sdk_schemas(scope), key=lambda item: item["name"])
        if runtime.language == "python":
            methods = []
            for schema in schemas:
                methods.append("    async def %s(self, args: Dict[str, Any]) -> Any: ..." % schema["name"])
            return ("## Writing code for run_code\n\n```python\n"
                    "from typing import Any, Dict\n\nclass Tools:\n%s\n\ntools: Tools\n```" %
                    ("\n".join(methods) if methods else "    pass"))
        members = ["  %s: (args: unknown) => Promise<unknown>;" % schema["name"]
                   for schema in schemas]
        return ("## Writing code for run_code\n\n```ts\ndeclare const tools: {\n%s\n};\n```" %
                "\n".join(members))

    def _register(self, tool_or_spec: Union[Tool, Dict[str, Any], str, None] = None,
                 description: Optional[str] = None,
                 parameters: Optional[Dict[str, Any]] = None,
                 handler: Optional[Callable[..., Any]] = None,
                 execution_mode: str = "parallel",
                 present_call: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 present_result: Optional[Callable[[Any], Any]] = None,
                 name: Optional[str] = None) -> Callable[[], None]:
        spec_name = name or (tool_or_spec if isinstance(tool_or_spec, str) else None)
        if isinstance(tool_or_spec, Tool):
            tool = tool_or_spec
        elif isinstance(tool_or_spec, dict):
            definition = tool_or_spec
            timeout_ms = definition.get("timeoutMs", definition.get("timeout_ms"))
            if timeout_ms is not None and (not isinstance(timeout_ms, (int, float)) or timeout_ms <= 0):
                raise ValueError('tool "%s" timeoutMs must be a positive finite number' % definition.get("name", ""))
            canonical = definition.get("output") is not None
            tool = Tool(
                definition.get("name") or spec_name or "",
                definition.get("description", description or ""),
                definition.get("parameters", parameters or {}),
                definition.get("execute") or definition.get("handler") or handler,
                definition.get("execution_mode", execution_mode),
                definition.get("presentCall") or definition.get("present_call") or present_call,
                definition.get("presentResult") or definition.get("present_result") or present_result,
                definition.get("output"),
                definition.get("finalizeContent") or definition.get("finalize_content"),
                timeout_ms,
                definition.get("isConcurrencySafe") or definition.get("is_concurrency_safe"),
                canonical,
            )
        elif spec_name and (handler is not None or callable(tool_or_spec)):
            tool = Tool(spec_name, description or "", parameters or {},
                        handler or tool_or_spec, execution_mode, present_call, present_result)
        else:
            raise ValueError("Invalid tool registration spec: %r, name=%r" % (tool_or_spec, name))
        self._validate_definition(tool)
        return self._insert(tool)

    def register(self, definition: Dict[str, Any]) -> Callable[[], None]:
        """Register one strict upstream canonical definition."""
        return self.register_canonical(definition)

    def register_canonical(self, definition: Dict[str, Any]) -> Callable[[], None]:
        if not isinstance(definition, dict) or definition.get("output") is None:
            name = definition.get("name", "") if isinstance(definition, dict) else ""
            raise TypeError('tool "%s" must declare output { schema, render, presentationMeta? }' % name)
        return self._register(definition)

    def register_legacy(
        self,
        tool_or_spec: Union[Tool, Dict[str, Any], str, None] = None,
        description: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        handler: Optional[Callable[..., Any]] = None,
        execution_mode: str = "parallel",
        present_call: Optional[Callable[[Dict[str, Any]], Any]] = None,
        present_result: Optional[Callable[[Any], Any]] = None,
        name: Optional[str] = None,
    ) -> Callable[[], None]:
        return self._register(
            tool_or_spec, description, parameters, handler, execution_mode,
            present_call, present_result, name)

    def _validate_definition(self, tool: Tool) -> None:
        if not tool.name or not callable(tool.handler):
            raise ValueError("tool name and handler are required")
        if not isinstance(tool.parameters, dict):
            raise TypeError('tool "%s" parameters must be a JSON schema object' % tool.name)
        if tool.canonical:
            output = tool.output
            if (not isinstance(output, dict) or not isinstance(output.get("schema"), dict)
                    or not callable(output.get("render"))
                    or (output.get("presentationMeta") is not None
                        and not callable(output.get("presentationMeta")))):
                raise TypeError('tool "%s" output must declare { schema, render, presentationMeta? }' % tool.name)
            _assert_supported_schema(tool.parameters, "parameters")
            _assert_supported_schema(output["schema"], "output.schema")
        if tool.timeout_ms is not None and (
                isinstance(tool.timeout_ms, bool)
                or not isinstance(tool.timeout_ms, (int, float))
                or not math.isfinite(tool.timeout_ms)
                or tool.timeout_ms <= 0):
            raise ValueError('tool "%s" timeoutMs must be a positive finite number' % tool.name)

    def _insert(self, tool: Tool) -> Callable[[], None]:
        if tool.name == RUN_CODE_NAME:
            raise ValueError('tool name "%s" is reserved for the Code Mode presentation transport and cannot be registered or shadowed' % RUN_CODE_NAME)
        owner_ctx = self._current_scope_context()
        layer = self._layer_for(owner_ctx, create=True)
        assert layer is not None
        if tool.name in layer.tools:
            suffix = "" if owner_ctx is None else " in this scope"
            raise ValueError('tool "%s" is already registered%s' % (tool.name, suffix))
        layer.tools[tool.name] = tool
        disposed = False

        def disposer() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            if layer.tools.get(tool.name) is tool:
                del layer.tools[tool.name]
                if owner_ctx is not None and not layer.tools and not layer.restrictions and not layer.guards and layer.mode is None:
                    self._scoped_layers.pop(owner_ctx, None)
                self.ctx.emit("tools/change")

        self.ctx.emit("tools/change")
        self._register_owned_cleanup(self.ctx, disposer, "tools.register()")
        return disposer

    def register_tool(self, tool_or_spec: Union[Tool, Dict[str, Any]]) -> Callable[[], None]:
        return self.register_legacy(tool_or_spec)

    def get_tool(self, name: str, scope: Any = None) -> Optional[Tool]:
        return self._view(scope)["visible"].get(name)

    def get(self, name: str, scope: Any = None) -> Optional[Tool]:
        return self.get_tool(name, scope)

    def has_tool(self, name: str, scope: Any = None) -> bool:
        return self.get_tool(name, scope) is not None

    def has(self, name: str, scope: Any = None) -> bool:
        return self.has_tool(name, scope)

    def list_tools(self, scope: Any = None) -> List[Tool]:
        return list(self._view(scope)["visible"].values())

    def schemas(self, scope: Optional[Any] = None) -> List[Dict[str, Any]]:
        mode = self._mode_for(scope)
        if mode != "native":
            self._require_code_runtime(mode)
        projected = []
        for tool in self._view(scope)["visible"].values():
            try:
                parameters = _json_snapshot(tool.parameters)
            except Exception:
                raise TypeError('tool "%s" parameters must be lossless JSON before schema projection' % tool.name)
            projected.append({"name": tool.name, "description": tool.description,
                              "parameters": parameters})
        if mode == "code":
            return [schema for schema in projected if schema["name"] == RUN_CODE_NAME]
        return projected

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    def get_schemas(self) -> List[Dict[str, Any]]:
        return self.get_tool_definitions()

    def execution_mode(self, exec_input: Union[ToolExecutionInput, Dict[str, Any]]) -> Dict[str, str]:
        name = exec_input.name if isinstance(exec_input, ToolExecutionInput) else exec_input.get("name", "")
        arguments = exec_input.arguments if isinstance(exec_input, ToolExecutionInput) else exec_input.get("arguments", {})
        agent = exec_input.agent if isinstance(exec_input, ToolExecutionInput) else exec_input.get("agent")
        tool = self.get_tool(name, agent)
        if tool is None:
            return {"kind": "exclusive"}
        if tool.concurrency_classifier is not None:
            if tool.validate_arguments(arguments):
                return {"kind": "exclusive"}
            try:
                return {"kind": "parallel" if tool.concurrency_classifier(arguments) is True else "exclusive"}
            except Exception:
                return {"kind": "exclusive"}
        return {"kind": tool.execution_mode if not tool.canonical else "exclusive"}

    def restrict(self, restriction: Dict[str, Any]) -> Callable[[], None]:
        owner_ctx = self._current_scope_context()
        if owner_ctx is None:
            raise RuntimeError("tools.restrict() requires a scoped context")
        allow = restriction.get("allow")
        deny = restriction.get("deny")
        if allow is None and deny is None:
            raise ValueError("tools.restrict({}) is a no-op")
        names = list(allow or []) + list(deny or [])
        if RUN_CODE_NAME in names:
            raise ValueError('tools.restrict() cannot name reserved Code Mode presentation transport "%s"' % RUN_CODE_NAME)
        known = self._view(owner_ctx)["restrictable"]
        unknown = [name for name in names if name not in known]
        if unknown:
            raise ValueError("tools.restrict() names unknown global tool%s %s" % (
                "s" if len(unknown) != 1 else "", ", ".join('"%s"' % name for name in unknown)))
        layer = self._layer_for(owner_ctx, create=True)
        assert layer is not None
        compiled = {"allow": set(allow) if allow is not None else None,
                    "deny": set(deny) if deny is not None else None}
        layer.restrictions.append(compiled)
        active = True

        def dispose() -> None:
            nonlocal active
            if not active:
                return
            active = False
            if compiled in layer.restrictions:
                layer.restrictions.remove(compiled)
            self.ctx.emit("tools/change")

        self.ctx.emit("tools/change")
        self._register_owned_cleanup(self.ctx, dispose, "tools.restrict()")
        return dispose

    def guard(self, callback: Callable[[ToolRunContext], Optional[str]]) -> Callable[[], None]:
        owner_ctx = self._current_scope_context()
        layer = self._layer_for(owner_ctx, create=True)
        assert layer is not None
        layer.guards.append(callback)
        active = True

        def dispose() -> None:
            nonlocal active
            if not active:
                return
            active = False
            if callback in layer.guards:
                layer.guards.remove(callback)

        self._register_owned_cleanup(self.ctx, dispose, "tools.guard()")
        return dispose

    def _guard_reason(self, exec_input: ToolRunContext) -> Optional[str]:
        for callback in self._global_layer.guards:
            reason = callback(exec_input)
            if reason is not None:
                return reason
        for scope_ctx in self._scope_chain(exec_input.agent):
            layer = self._layer_for(scope_ctx)
            if layer is None:
                continue
            for callback in layer.guards:
                reason = callback(exec_input)
                if reason is not None:
                    return reason
        return None

    def present_as(self, mode: str) -> Callable[[], None]:
        if mode not in ("native", "code", "both"):
            raise ValueError("tools presentation mode must be native, code, or both")
        owner_ctx = self._current_scope_context()
        if owner_ctx is None:
            raise RuntimeError("tools.presentAs() requires a scoped context")
        layer = self._layer_for(owner_ctx, create=True)
        assert layer is not None
        if layer.mode is not None:
            raise RuntimeError('tools.presentAs("%s") conflicts with "%s" already declared for this scope' % (mode, layer.mode))
        layer.mode = mode
        prompt_disposers: List[Callable[[], None]] = []
        if mode != "native":
            system_prompt = self._optional_service("systemPrompt")
            try:
                prompt_disposers = self._mount_code_prompt_sections(system_prompt)
            except Exception:
                layer.mode = None
                for prompt_disposer in reversed(prompt_disposers):
                    prompt_disposer()
                raise
        active = True

        def dispose() -> None:
            nonlocal active
            if not active:
                return
            active = False
            for prompt_disposer in reversed(prompt_disposers):
                prompt_disposer()
            if layer.mode == mode:
                layer.mode = None
            self.ctx.emit("tools/change")

        self.ctx.emit("tools/change")
        self._register_owned_cleanup(self.ctx, dispose, "tools.presentAs()")
        return dispose

    def presentAs(self, mode: str) -> Callable[[], None]:
        return self.present_as(mode)

    def _carrier(self, exec_input: ToolExecutionInput) -> Any:
        agent_ctx = getattr(exec_input.agent, "ctx", None)
        return agent_ctx if agent_ctx is not None else self.ctx

    async def prepare(self, exec_input: ToolExecutionInput) -> Dict[str, Any]:
        visible = self.get_tool(exec_input.name, exec_input.agent)
        captured_finalizer = visible.finalize_content if visible is not None else None
        try:
            exec_ctx = ToolRunContext(exec_input)
            exec_ctx._finalizer = captured_finalizer
        except Exception as error:
            fallback = ToolRunContext(ToolExecutionInput(
                exec_input.call_id, exec_input.name, {}, agent=exec_input.agent,
                signal=exec_input.signal, session=exec_input.session,
                root_call_id=exec_input.root_call_id, parent=exec_input.parent,
                metadata=exec_input.metadata))
            fallback._finalizer = captured_finalizer
            return {"kind": "final-result", "exec": fallback, "result": _error_result(error)}
        try:
            if self._is_aborted(exec_ctx._caller_signal):
                result = self._aborted_before_result()
                exec_ctx._prepared_kind = "final-result"
                exec_ctx._prepared_result = result
                return {"kind": "final-result", "exec": exec_ctx, "result": result}
            if (visible is not None and self._mode_for(exec_ctx.agent) == "code"
                    and exec_ctx.parent is None and exec_ctx.name != RUN_CODE_NAME):
                result = _error_result(ToolNotFoundError(
                    exec_ctx.name,
                    "only `run_code` is callable directly - call `%s` from inside a `run_code` program instead" % exec_ctx.name))
                exec_ctx._prepared_kind = "final-result"
                exec_ctx._prepared_result = result
                exec_ctx._finalizer = None
                return {"kind": "final-result", "exec": exec_ctx, "result": result}
            decision = await self._carrier(exec_ctx).waterfall(
                "tools/pre-execute", exec_ctx, lambda *_args: {"kind": "allow"})
            if not isinstance(decision, dict):
                raise TypeError("tools/pre-execute must return a decision")
            kind = decision.get("kind")
            if kind == "ask":
                decision = await self._resolve_ask(exec_ctx, decision)
                kind = "deny"
                if decision.get("kind") == "allow":
                    kind = "allow"
                if exec_ctx._approval_cancelled and self._is_aborted(exec_ctx._caller_signal):
                    result = self._aborted_before_result()
                    exec_ctx._prepared_kind = "post-result"
                    exec_ctx._prepared_result = result
                    return {"kind": "post-result", "exec": exec_ctx, "result": result}
            if kind == "deny":
                reason = decision.get("reason") or "tool call denied"
                result = ToolExecutionResult([{"type": "text", "text": "Error: %s" % reason}],
                                             is_error=True, error={"message": reason})
                exec_ctx._prepared_kind = "post-result"
                exec_ctx._prepared_result = result
                return {"kind": "post-result", "exec": exec_ctx, "result": result}
            if kind != "allow":
                raise TypeError("unknown tools/pre-execute decision %r" % kind)
            guard_reason = self._guard_reason(exec_ctx)
            if guard_reason is not None:
                result = ToolExecutionResult(
                    [{"type": "text", "text": "Error: %s" % guard_reason}],
                    is_error=True, error={"message": guard_reason})
                exec_ctx._prepared_kind = "post-result"
                exec_ctx._prepared_result = result
                return {"kind": "post-result", "exec": exec_ctx, "result": result}
            if self._is_aborted(exec_ctx.signal):
                result = self._aborted_before_result()
                exec_ctx._prepared_kind = "post-result"
                exec_ctx._prepared_result = result
                return {"kind": "post-result", "exec": exec_ctx, "result": result}
            return {"kind": "dispatch", "exec": exec_ctx}
        except Exception as error:
            result = _error_result(error)
            exec_ctx._prepared_kind = "final-result"
            exec_ctx._prepared_result = result
            return {"kind": "final-result", "exec": exec_ctx, "result": result}

    async def dispatch(self, exec_input: ToolRunContext) -> Dict[str, Any]:
        if exec_input._prepared_result is not None:
            return {"kind": exec_input._prepared_kind, "result": exec_input._prepared_result}
        try:
            result = await self._carrier(exec_input).waterfall(
                "tools/execute", exec_input, lambda *_args: self._dispatch_body(exec_input))
            normalized = self._normalize_dispatch_result(exec_input, result)
            normalized = self._copy_result(
                normalized,
                additional_contexts=(list(exec_input._additional_contexts)
                                     + list(normalized.additional_contexts)),
                concludes_turn=(exec_input._concludes_turn and not normalized.is_error)
                or normalized.concludes_turn,
            )
            if self._is_aborted(exec_input._caller_signal) and not normalized.is_error:
                normalized = (self._aborted_result(normalized) if exec_input._body_invoked
                              else self._aborted_before_result())
            return {"kind": "post-result", "result": normalized.freeze()}
        except Exception as error:
            return {"kind": "final-result", "result": _error_result(error)}

    async def _dispatch_body(self, exec_input: ToolRunContext) -> ToolExecutionResult:
        wrapper_signal = exec_input.signal
        fused_signal = (exec_input._caller_signal if wrapper_signal is exec_input._caller_signal
                        else _FusedSignal(exec_input._caller_signal, wrapper_signal))
        if fused_signal.is_set():
            return self._aborted_before_result()
        exec_input.signal = fused_signal
        tool = self.get_tool(exec_input.name, exec_input.agent)
        if tool is None:
            exec_input.signal = wrapper_signal
            return _error_result(ToolNotFoundError(exec_input.name))
        try:
            try:
                exec_input._body_invoked = True
                raw = await tool.execute(exec_input.arguments, exec_input, self.ctx)
            except Exception as error:
                return _error_result(error).freeze()
            try:
                if tool.output is None:
                    return ToolExecutionResult.from_raw(raw).freeze()
                value = _json_snapshot(raw)
                violations = _schema_violations(value, tool.output.get("schema", {}), "value")
                if violations:
                    raise ToolOutputError(tool.name, violations)
                content = _json_snapshot(tool.output["render"](exec_input.arguments, value))
                meta = None
                projector = tool.output.get("presentationMeta")
                if projector is not None and exec_input.parent is None:
                    meta = _json_snapshot(projector(exec_input.arguments, value))
                result = ToolExecutionResult(content=content, value=value, meta=meta)
                result._execution_token = exec_input.token
                result = self._aborted_result(result) if fused_signal.is_set() else result
                return result.freeze()
            except Exception as error:
                if not isinstance(error, ToolOutputError):
                    error = ToolOutputError(
                        tool.name, ["output projection failed: %s" % _error_message(error)])
                return _error_result(error).freeze()
        finally:
            exec_input.signal = wrapper_signal

    def _normalize_dispatch_result(self, exec_input: ToolRunContext, raw: Any) -> ToolExecutionResult:
        result = ToolExecutionResult.from_raw(raw)
        if getattr(result, "_execution_token", None) is exec_input.token:
            return result
        if result.is_error:
            return result
        tool = self.get_tool(exec_input.name, exec_input.agent)
        if tool is None:
            return _error_result(ToolNotFoundError(exec_input.name))
        if not tool.canonical:
            return result
        try:
            value = _json_snapshot(result.value)
            violations = _schema_violations(value, tool.output.get("schema", {}), "value")
            if violations:
                raise ToolOutputError(tool.name, violations)
            content = _json_snapshot(tool.output["render"](exec_input.arguments, value))
            meta = None
            projector = tool.output.get("presentationMeta")
            if projector is not None and exec_input.parent is None:
                meta = _json_snapshot(projector(exec_input.arguments, value))
            normalized = ToolExecutionResult(content, value=value, meta=meta,
                                               additional_contexts=result.additional_contexts,
                                               concludes_turn=result.concludes_turn)
            return normalized
        except Exception as error:
            if not isinstance(error, ToolOutputError):
                error = ToolOutputError(tool.name, ["output projection failed: %s" % _error_message(error)])
            return _error_result(error)

    @staticmethod
    def _copy_result(result: ToolExecutionResult, **changes: Any) -> ToolExecutionResult:
        values = {
            "content": result.content,
            "is_error": result.is_error,
            "error": result.error,
            "meta": result.meta,
            "concludes_turn": result.concludes_turn,
            "additional_contexts": result.additional_contexts,
            "value": result.value,
        }
        values.update(changes)
        return ToolExecutionResult(**values)

    async def _resolve_ask(self, exec_input: ToolRunContext,
                           decision: Dict[str, Any]) -> Dict[str, Any]:
        approval = self._optional_service("approval")
        if approval is None:
            return {"kind": "deny", "reason": decision.get("reason") or "tool call requires approval"}
        if exec_input.agent is None:
            return {"kind": "deny", "reason": 'tool "%s" requires approval, but the call has no agent to route it through' % exec_input.name}
        request = {"agent": exec_input.agent, "toolName": exec_input.name,
                   "callId": exec_input.call_id, "signal": exec_input.signal}
        if decision.get("reason") is not None:
            request["reason"] = decision["reason"]
        if hasattr(approval, "request"):
            outcome = approval.request(request)
            outcome = await outcome if inspect.isawaitable(outcome) else outcome
            if outcome == "allowed-once":
                return {"kind": "allow"}
            if outcome == "rejected":
                return {"kind": "deny", "reason": 'the user rejected tool "%s"' % exec_input.name}
            if outcome == "cancelled":
                exec_input._approval_cancelled = True
                return {"kind": "deny", "reason": 'approval for tool "%s" was cancelled' % exec_input.name}
            return {"kind": "deny", "reason": 'tool "%s" requires approval, but no approval channel is available' % exec_input.name}
        if hasattr(approval, "request_approval"):
            allowed = approval.request_approval(exec_input.name, request)
            allowed = await allowed if inspect.isawaitable(allowed) else allowed
            return {"kind": "allow"} if allowed else {"kind": "deny", "reason": decision.get("reason") or "tool call requires approval"}
        return {"kind": "deny", "reason": decision.get("reason") or "tool call requires approval"}

    async def finalize(self, exec_input: ToolRunContext,
                       result: ToolExecutionResult) -> ToolExecutionResult:
        try:
            result.freeze()
            decision = await self._carrier(exec_input).waterfall(
                "tools/post-execute", exec_input, result,
                lambda *_args: {"kind": "accept"})
            result = self._apply_post_decision(exec_input, result, decision)
            if self._is_aborted(exec_input._caller_signal) and not result.is_error:
                result = self._aborted_result(result)
        except Exception as error:
            result = _error_result(error)
        return self.finish(exec_input, result)

    def _apply_post_decision(self, exec_input: ToolRunContext,
                             result: ToolExecutionResult, decision: Any) -> ToolExecutionResult:
        if not isinstance(decision, dict):
            raise TypeError("tools/post-execute must return a decision")
        contexts = _decision_contexts(decision)
        if decision.get("kind") == "block":
            feedback = decision.get("feedback", [])
            message = "\n".join(block.get("text", "[%s content]" % block.get("type", "unknown"))
                                for block in feedback if isinstance(block, dict))
            message = message or "tool result blocked by post-execute policy"
            return ToolExecutionResult(feedback, is_error=True, error={"message": message},
                                       additional_contexts=contexts)
        if decision.get("kind") != "accept":
            raise TypeError("unknown tools/post-execute decision %r" % decision.get("kind"))
        if "content" in decision and "value" in decision:
            raise TypeError("tools/post-execute accept decision cannot replace both value and content")
        if "value" in decision:
            if result.is_error:
                raise TypeError("tools/post-execute cannot replace the value of a failed result")
            tool = self.get_tool(exec_input.name, exec_input.agent)
            if tool is None:
                raise ToolNotFoundError(exec_input.name)
            if tool.output is None:
                result = ToolExecutionResult.from_raw(decision["value"])
            else:
                try:
                    value = _json_snapshot(decision["value"])
                    violations = _schema_violations(value, tool.output.get("schema", {}), "value")
                    if violations:
                        raise ToolOutputError(tool.name, violations)
                    content = _json_snapshot(tool.output["render"](exec_input.arguments, value))
                    meta = None
                    projector = tool.output.get("presentationMeta")
                    if projector is not None and exec_input.parent is None:
                        meta = _json_snapshot(projector(exec_input.arguments, value))
                    result = ToolExecutionResult(
                        content, value=value, meta=meta,
                        additional_contexts=result.additional_contexts,
                        concludes_turn=result.concludes_turn)
                except Exception as error:
                    if isinstance(error, ToolOutputError):
                        raise
                    raise ToolOutputError(
                        tool.name, ["output projection failed: %s" % _error_message(error)])
        elif "content" in decision:
            result = self._copy_result(result, content=_json_snapshot(decision["content"]))
        return self._copy_result(
            result, additional_contexts=list(result.additional_contexts) + contexts)

    def finish(self, exec_input: ToolRunContext,
               result: ToolExecutionResult) -> ToolExecutionResult:
        result = self._copy_result(result)
        finalizer = exec_input._finalizer
        try:
            result.content = _json_snapshot(result.content)
            if result.meta is not None:
                result.meta = _json_snapshot(result.meta)
            result.additional_contexts = _json_snapshot(result.additional_contexts)
        except Exception as error:
            result = _error_result(error)
        if finalizer is not None:
            try:
                finalizer_result = self._copy_result(result).freeze()
                content = finalizer(exec_input, finalizer_result)
                if content is not None:
                    result = self._copy_result(result, content=_json_snapshot(content))
            except Exception as error:
                result = _error_result(error)
        try:
            result.content = _json_snapshot(result.content)
            if result.meta is not None:
                result.meta = _json_snapshot(result.meta)
            result.additional_contexts = _json_snapshot(result.additional_contexts)
        except Exception as error:
            result = _error_result(error)
        result.freeze()
        self._notify_result(exec_input, result)
        return result

    def _notify_result(self, exec_input: ToolRunContext, result: ToolExecutionResult) -> None:
        carrier = self._carrier(exec_input)
        try:
            callbacks = carrier.events._dispatch_hooks(
                "emit", "tools/result", carrier, [exec_input, result])
        except Exception:
            callbacks = []
        logger = self._optional_service("logger")

        def report(error: BaseException) -> None:
            if logger is not None and hasattr(logger, "warn"):
                logger.warn('tool "%s" (%s): tools/result observer failed: %s' %
                            (exec_input.name, exec_input.call_id, _error_message(error)))

        def settled(done: asyncio.Future) -> None:
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                report(error)

        for callback in callbacks:
            try:
                returned = callback(exec_input, result)
                if inspect.isawaitable(returned):
                    task = asyncio.ensure_future(returned)
                    task.add_done_callback(settled)
            except Exception as error:
                report(error)

    async def execute(self, exec_input: ToolExecutionInput) -> ToolExecutionResult:
        prepared = await self.prepare(exec_input)
        if prepared["kind"] == "dispatch":
            dispatched = await self.dispatch(prepared["exec"])
            if dispatched["kind"] == "post-result":
                return await self.finalize(prepared["exec"], dispatched["result"])
            return self.finish(prepared["exec"], dispatched["result"])
        if prepared["kind"] == "post-result":
            return await self.finalize(prepared["exec"], prepared["result"])
        return self.finish(prepared["exec"], prepared["result"])

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        result = await self.execute(ToolExecutionInput(
            "call-%s" % tool_name, tool_name, arguments, signal=asyncio.Event()))
        return "".join(block.get("text", "") for block in result.content
                       if isinstance(block, dict) and block.get("type") == "text")

    @staticmethod
    def _is_aborted(signal: Any) -> bool:
        if signal is None:
            return False
        checker = getattr(signal, "is_set", None)
        return bool(checker()) if callable(checker) else bool(getattr(signal, "aborted", False))

    @staticmethod
    def _aborted_before_result() -> ToolExecutionResult:
        message = "tool call aborted before dispatch"
        return ToolExecutionResult(
            [{"type": "text", "text": "Error: %s" % message}], is_error=True,
            error={"message": message, "name": "AbortError",
                   "code": TOOL_ABORTED_BEFORE_DISPATCH,
                   "info": {"name": "AbortError", "code": TOOL_ABORTED_BEFORE_DISPATCH}})

    @staticmethod
    def _aborted_result(prior: Optional[ToolExecutionResult] = None) -> ToolExecutionResult:
        message = "tool call aborted"
        return ToolExecutionResult(
            [{"type": "text", "text": "Error: %s" % message}], is_error=True,
            error={"message": message, "name": "AbortError", "code": TOOL_ABORTED,
                   "info": {"name": "AbortError", "code": TOOL_ABORTED}},
            additional_contexts=list(prior.additional_contexts) if prior is not None else [])


class ToolsPlugin(Plugin):
    id = "tools"
    name = "@deepseek-ai/dsh-tools"
    # The host composition may omit the optional system-prompt registry
    # (notably minimal mode).  ToolsService already treats it as optional
    # when mounting guidance sections, so it must not block activation.
    inject = []

    def apply(self, ctx: Any) -> None:
        if not ctx.has("tools"):
            ctx.provide("tools", ToolsService(ctx, config=self.config))


ToolRegistry = ToolsService

__all__ = [
    "RUN_CODE_NAME", "TOOL_ABORTED", "TOOL_ABORTED_BEFORE_DISPATCH",
    "TOOL_RUNTIME_SCHEDULER", "TOOL_NOT_FOUND", "TOOL_ARGS_INVALID",
    "CodeRunFailedError", "Tool", "ToolArgsError", "ToolExecutionInput",
    "ToolExecutionResult", "ToolNotFoundError", "ToolOutputError", "ToolRegistry",
    "ToolRunContext", "ToolsPlugin", "ToolsService",
]
