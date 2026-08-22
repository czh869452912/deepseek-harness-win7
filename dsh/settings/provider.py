"""
Abstract SettingsProvider base service.
Aligned 1:1 with reference @deepseek-ai/dsh-settings/src/index.ts.
"""

import copy
import math
from typing import Any, Callable, Dict, List, Optional, Set, Union
from dsh.cordis.service import Service
from dsh.settings.redact import redact_secrets
from dsh.settings.types import settings_namespace


class SettingsDescriptor:
    """One registered namespace as surfaced to configuration UIs."""

    def __init__(
        self,
        ns: str,
        schema: Any,
        value: Any,
        revision: int,
        applies: str = "live",
        base: Optional[Any] = None,
        user: Optional[Any] = None,
        secrets: Optional[List[Any]] = None,
    ):
        self.ns = ns
        self.schema = schema
        self.value = value
        self.revision = revision
        self.applies = applies
        self.base = base
        self.user = user
        self.secrets = secrets

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "ns": self.ns,
            "schema": self.schema,
            "value": self.value,
            "revision": self.revision,
            "applies": self.applies,
        }
        if self.base is not None:
            d["base"] = self.base
        if self.user is not None:
            d["user"] = self.user
        if self.secrets is not None:
            d["secrets"] = self.secrets
        return d


class SettingsConflictError(ValueError):
    """Raised when a settings write expected revision does not match actual revision."""

    def __init__(self, ns: str, expected: int, actual: int):
        super().__init__(
            f'settings namespace "{ns}" changed since it was read (expected revision {expected}, now {actual})'
        )
        self.code = "SETTINGS_CONFLICT"
        self.ns = ns
        self.expected = expected
        self.actual = actual


def deep_equal_json(a: Any, b: Any) -> bool:
    """Deep structural equality over JSON-compatible values."""
    if a is b:
        return True
    if type(a) != type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return False
    if isinstance(a, dict):
        if not isinstance(b, dict):
            return False
        if set(a.keys()) != set(b.keys()):
            return False
        return all(deep_equal_json(a[k], b[k]) for k in a)
    if isinstance(a, list):
        if not isinstance(b, list):
            return False
        if len(a) != len(b):
            return False
        return all(deep_equal_json(x, y) for x, y in zip(a, b))
    return a == b


def is_plain_object(val: Any) -> bool:
    """Whether a value is a plain dictionary mapping."""
    return isinstance(val, dict)


def apply_path_op(section: dict, op: dict) -> dict:
    """
    Apply one path op ({op: 'set'|'unset', path: List[str], value?: Any}) to a section dict.
    Empty path [] addresses the section root.
    """
    sec = copy.deepcopy(section) if is_plain_object(section) else {}
    kind = op.get("op")
    path = op.get("path") or []

    if not path:
        if kind == "unset":
            return {}
        val = op.get("value")
        if not is_plain_object(val):
            raise TypeError("settings mutate: setting the section root requires a plain object")
        return copy.deepcopy(val)

    head = str(path[0])
    rest = path[1:]

    if not rest:
        if kind == "set":
            sec[head] = copy.deepcopy(op.get("value"))
        elif kind == "unset":
            sec.pop(head, None)
        return sec

    child = sec.get(head)
    if not is_plain_object(child):
        if kind == "unset":
            return sec
        child = {}
    sec[head] = apply_path_op(child, {"op": kind, "path": rest, "value": op.get("value")})
    return sec


def _describe_rejected(value: Any) -> str:
    if value is None:
        return "None"
    return f"a {type(value).__name__}"


def clone_json_shaped(root: Dict[str, Any], reject: Callable[[str, str], TypeError]) -> Dict[str, Any]:
    """
    Detach and validate write input in a single walk before persistence.
    Only JSON data (dicts, lists, strings, finite numbers, booleans, None) allowed.
    """
    visiting = set()

    def _clone(val: Any, path: str) -> Any:
        if val is None or isinstance(val, (str, bool)):
            return val
        if isinstance(val, (int, float)):
            if math.isnan(val) or math.isinf(val):
                raise reject("a non-finite number", path)
            return val
        if isinstance(val, list):
            obj_id = id(val)
            if obj_id in visiting:
                raise reject("a circular reference", path)
            visiting.add(obj_id)
            try:
                return [_clone(entry, f"{path}[{i}]") for i, entry in enumerate(val)]
            finally:
                visiting.remove(obj_id)
        if is_plain_object(val):
            obj_id = id(val)
            if obj_id in visiting:
                raise reject("a circular reference", path)
            visiting.add(obj_id)
            try:
                out = {}
                for k, entry in val.items():
                    if entry is None:
                        continue
                    out[str(k)] = _clone(entry, f"{path}.{k}")
                return out
            finally:
                visiting.remove(obj_id)
        raise reject(_describe_rejected(val), path)

    return _clone(root, "$")


def merge_layers(under: Any, over: Any) -> Any:
    """
    Layer 'over' onto 'under': plain objects merge recursively,
    every other value (lists included) replaces the lower layer wholesale.
    """
    if over is None:
        return under
    if not is_plain_object(under) or not is_plain_object(over):
        return over
    merged = copy.deepcopy(under)
    for key, value in over.items():
        if value is None:
            continue
        merged[key] = merge_layers(merged[key], value) if key in merged else copy.deepcopy(value)
    return merged


def deep_freeze(val: Any) -> Any:
    """Return a detached snapshot of the resolved value."""
    return copy.deepcopy(val)


class SettingsWatcher:

    def __init__(self, callback: Callable):
        self.callback = callback
        self.active = True


class SettingsScope:
    """Owner-facing handle for one registered namespace."""

    def __init__(self, provider: "SettingsProvider", ns: str):
        self.provider = provider
        self.ns = ns

    def get(self) -> Any:
        return self.provider.get(self.ns)

    def watch(self, callback: Callable) -> Callable[[], None]:
        return self.provider.watch_scope(self.ns, callback)

    def update(self, patch: dict, expected_revision: Optional[int] = None) -> Any:
        return self.provider.update(self.ns, patch, expected_revision=expected_revision)

    def replace(self, section: dict, expected_revision: Optional[int] = None) -> Any:
        return self.provider.replace(self.ns, section, expected_revision=expected_revision)

    def mutate(self, ops: List[dict], expected_revision: Optional[int] = None) -> Any:
        return self.provider.mutate(self.ns, ops, expected_revision=expected_revision)


class SettingsRegistration:

    def __init__(
        self,
        ns: str,
        schema: Any = None,
        base: Any = None,
        applies: str = "live",
        validate: Optional[Callable[[Any], None]] = None,
    ):
        self.ns = ns
        self.schema = schema
        self.base = base
        self.applies = applies
        self.validate = validate
        self.resolved: Any = None
        self.revision: int = 1
        self.watchers: Set[SettingsWatcher] = set()


class SettingsProvider(Service):
    """
    Abstract settings service capability seam (`ctx.settings`).
    Base class owns namespace registration, resolution, validation,
    change detection, revision tracking, and event emission.
    """

    def __init__(self, ctx: Optional[Any] = None):
        super().__init__(ctx, "settings")
        self._registrations: Dict[str, SettingsRegistration] = {}
        self._document: Dict[str, Any] = {}
        self._stopped: bool = False

    @property
    def writable(self) -> bool:
        return True

    @property
    def document_path(self) -> Optional[str]:
        return None

    def prepare_document(self) -> Optional[str]:
        return self.document_path

    def _load_document(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _persist_section(self, ns: str, section: Dict[str, Any]) -> None:
        raise NotImplementedError

    def register(
        self,
        ns: str,
        schema: Any = None,
        base: Any = None,
        applies: str = "live",
        validate: Optional[Callable[[Any], None]] = None,
    ) -> SettingsScope:
        """Register a namespace schema and return its owner scope."""
        validated_ns = settings_namespace(ns)
        if validated_ns in self._registrations:
            raise ValueError(f'settings namespace "{validated_ns}" is already registered')

        reg = SettingsRegistration(
            ns=validated_ns,
            schema=schema,
            base=base,
            applies=applies,
            validate=validate,
        )

        sec = self._get_section(validated_ns)
        resolved_candidate = self._resolve(schema, base, sec, validate)
        reg.resolved = deep_freeze(resolved_candidate)
        reg.revision = 1

        self._registrations[validated_ns] = reg

        if self.ctx and hasattr(self.ctx, "effect"):
            try:
                def _effect():
                    yield lambda: self._registrations.pop(validated_ns, None)
                self.ctx.effect(_effect, f"settings.register({validated_ns})")
            except Exception:
                pass

        return SettingsScope(self, validated_ns)

    def describe(self, options: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Describe every registered namespace for configuration surfaces."""
        options = options or {}
        redact = bool(options.get("redactSecrets"))
        descriptors = []

        for ns, reg in self._registrations.items():
            user_sec: Optional[Dict[str, Any]] = None
            try:
                user_sec = self._get_section(ns)
            except Exception:
                user_sec = None

            base_val = copy.deepcopy(reg.base) if reg.base is not None else None
            user_val = copy.deepcopy(user_sec) if user_sec is not None else None
            resolved_val = copy.deepcopy(reg.resolved)

            schema_json = {}
            if hasattr(reg.schema, "to_json"):
                schema_json = reg.schema.to_json()
            elif hasattr(reg.schema, "toJSON"):
                schema_json = reg.schema.toJSON()
            elif isinstance(reg.schema, dict):
                schema_json = copy.deepcopy(reg.schema)

            descriptor: Dict[str, Any] = {
                "ns": ns,
                "schema": schema_json,
                "value": resolved_val,
                "revision": reg.revision,
                "applies": reg.applies,
            }
            if base_val is not None:
                descriptor["base"] = base_val
            if user_val is not None:
                descriptor["user"] = user_val

            if redact:
                redacted_res = redact_secrets(reg.schema, resolved_val)
                descriptor["value"] = redacted_res.value
                if base_val is not None:
                    descriptor["base"] = redact_secrets(reg.schema, base_val).value
                if user_val is not None:
                    descriptor["user"] = redact_secrets(reg.schema, user_val).value
                descriptor["secrets"] = [s.to_dict() for s in redacted_res.secrets]

            descriptors.append(descriptor)

        return descriptors

    def get(self, ns: str) -> Any:
        """Read one registered namespace's resolved value."""
        reg = self._registrations.get(ns)
        if reg is not None:
            return reg.resolved
        return self._document.get(ns)

    def watch_scope(self, ns: str, callback: Callable) -> Callable[[], None]:
        reg = self._registrations.get(ns)
        if not reg:
            reg = SettingsRegistration(ns=ns)
            self._registrations[ns] = reg
        watcher = SettingsWatcher(callback)
        reg.watchers.add(watcher)

        def dispose():
            watcher.active = False
            reg.watchers.discard(watcher)

        return dispose

    def update(self, ns: str, patch: dict, expected_revision: Optional[int] = None) -> Any:
        """Merge patch into namespace's user layer and persist."""
        return self._write(ns, patch, "merge", expected_revision=expected_revision)

    def replace(self, ns: str, section: dict, expected_revision: Optional[int] = None) -> Any:
        """Replace namespace's user section wholesale and persist."""
        return self._write(ns, section, "replace", expected_revision=expected_revision)

    def mutate(self, ns: str, ops: List[dict], expected_revision: Optional[int] = None) -> Any:
        """Apply path ops to namespace's user section and persist."""
        if not isinstance(ops, list):
            raise TypeError(f'settings mutate for "{ns}" must be a list of path ops')
        for op in ops:
            if not is_plain_object(op) or op.get("op") not in ("set", "unset"):
                raise TypeError(f'settings mutate for "{ns}" ops must be {{op:\'set\'|\'unset\', path}}')
            path = op.get("path")
            if not isinstance(path, list) or any(not isinstance(p, str) for p in path):
                raise TypeError(f'settings mutate for "{ns}" op paths must be lists of strings')
        return self._write(ns, ops, "mutate", expected_revision=expected_revision)

    def _write(self, ns: str, input_data: Any, mode: str, expected_revision: Optional[int] = None) -> Any:
        verb = "update" if mode == "merge" else ("replace" if mode == "replace" else "mutate")
        reg = self._registrations.get(ns)
        if reg is None:
            raise ValueError(f'settings namespace "{ns}" is not registered')
        if self._stopped:
            raise RuntimeError(f'settings service is disposed: "{ns}" cannot be written')
        if not self.writable:
            raise RuntimeError(f'settings provider is read-only: "{ns}" cannot be updated in-process')

        if mode == "mutate":
            payload = {"ops": input_data}
        else:
            if not is_plain_object(input_data):
                raise TypeError(f'settings {verb} for "{ns}" must be a plain object')
            payload = input_data

        snapshot = clone_json_shaped(
            payload,
            lambda label, path: TypeError(f'settings {verb} for "{ns}" must contain only JSON-compatible data (found {label} at {path})'),
        )

        current = self._get_section(ns) or {}

        if expected_revision is not None and expected_revision != reg.revision:
            raise SettingsConflictError(ns, expected_revision, reg.revision)

        if mode == "merge":
            section = merge_layers(current, snapshot)
        elif mode == "replace":
            section = snapshot
        else:
            ops_list = snapshot.get("ops") or []
            sec_acc = copy.deepcopy(current)
            for op in ops_list:
                sec_acc = apply_path_op(sec_acc, op)
            section = sec_acc

        next_resolved = deep_freeze(self._resolve(reg.schema, reg.base, section, reg.validate))

        self._persist_section(ns, section)
        self._document[ns] = section

        if self._registrations.get(ns) is reg and not self._stopped:
            self.bump_revision(reg, current, section)
            self.commit(reg, next_resolved, source="update")

    def publish(self, doc: Dict[str, Any], source: str = "provider") -> None:
        """Publish external raw document into registered namespaces and notify subscribers."""
        before_sections: Dict[str, Any] = {}
        for ns, reg in self._registrations.items():
            try:
                before_sections[ns] = self._get_section(ns)
            except Exception:
                before_sections[ns] = None

        self._document = copy.deepcopy(doc)

        for ns, reg in list(self._registrations.items()):
            sec = self._get_section(ns)
            try:
                next_val = deep_freeze(self._resolve(reg.schema, reg.base, sec, reg.validate))
            except Exception as e:
                self._log("warn", f'settings: keeping last good "{ns}" after invalid stored section: {e}')
                continue

            before_sec = before_sections.get(ns)
            after_sec = sec
            self.bump_revision(reg, before_sec, after_sec)
            self.commit(reg, next_val, source=source)

    def bump_revision(self, registration: SettingsRegistration, before: Any, after: Any) -> None:
        """Advance revision when raw section changes and emit document event."""
        if deep_equal_json(before, after):
            return
        registration.revision += 1
        self._emit_document_updated(registration.ns, registration.revision)

    def _emit_document_updated(self, ns: str, revision: int) -> None:
        if not self.ctx or not hasattr(self.ctx, "emit"):
            return
        try:
            self.ctx.emit("settings/document-updated", ns, revision)
        except Exception as e:
            if getattr(e, "code", None) == "INVARIANT":
                raise e
            self._log("warn", f'settings: document-updated listener for "{ns}" failed: {e}')

    def commit(self, registration: SettingsRegistration, next_val: Any, source: str) -> None:
        """Commit resolved value when changed: swap, notify watchers, emit event."""
        prev_val = registration.resolved
        if deep_equal_json(next_val, prev_val):
            return
        registration.resolved = next_val

        for watcher in list(registration.watchers):
            if watcher.active:
                try:
                    watcher.callback(next_val, prev_val)
                except Exception as e:
                    self._log("warn", f'settings: watcher for "{registration.ns}" failed: {e}')

        if self.ctx and hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("settings/updated", registration.ns, next_val, prev_val, source)
            except Exception as e:
                if getattr(e, "code", None) == "INVARIANT":
                    raise e
                self._log("warn", f'settings: a settings/updated listener for "{registration.ns}" failed: {e}')

    def _get_section(self, ns: str) -> Optional[Dict[str, Any]]:
        sec = self._document.get(ns)
        if sec is None:
            return None
        if not is_plain_object(sec):
            raise TypeError(f'settings section "{ns}" must be an object of keys')
        return sec

    def _resolve(self, schema: Any, base: Any, section: Optional[Dict[str, Any]], validate: Optional[Callable] = None) -> Any:
        merged = merge_layers(base, section)
        if schema is not None:
            if callable(schema):
                val = schema(merged)
            elif hasattr(schema, "parse"):
                val = schema.parse(merged)
            elif hasattr(schema, "evaluate"):
                val = schema.evaluate(merged)
            else:
                val = merged
        else:
            val = merged

        if validate is not None:
            validate(val)
        return val

    def _log(self, level: str, message: str) -> None:
        logger = getattr(self.ctx, "logger", None) if self.ctx else None
        if logger is not None:
            try:
                getattr(logger, level)(message)
                return
            except Exception:
                pass


def install_settings_section(
    ctx: Any,
    ns: str,
    schema: Any,
    entry: Any,
    hooks: Dict[str, Any],
) -> None:
    """
    Install the canonical optional-settings consumer wiring.
    Hooks dictionary must contain:
    - 'setSource': Callable[[Callable[[], T]], None]
    - 'onChange': Callable[[], None]
    - 'validate': Optional[Callable[[T], None]]
    """
    def _mount(sctx: Any):
        settings_svc = sctx.get("settings") if hasattr(sctx, "get") else getattr(sctx, "settings", None)
        if not settings_svc:
            return
        validate_fn = hooks.get("validate")
        scope = settings_svc.register(ns, schema, base=entry, validate=validate_fn)
        hooks["setSource"](lambda: scope.get())

        if hasattr(sctx, "effect"):
            def _effect():
                yield lambda: (hooks["setSource"](lambda: entry), hooks["onChange"]())
            sctx.effect(_effect, f"installSettingsSection({ns})")

        hooks["onChange"]()
        scope.watch(lambda _next, _prev: hooks["onChange"]())

    if hasattr(ctx, "inject"):
        ctx.inject(["settings"], _mount)
