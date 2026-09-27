"""
Abstract settings service (`ctx.settings`).
Aligned 1:1 with reference @deepseek-ai/dsh-settings/src/index.ts.

Language adaptations, recorded where they apply:

* JavaScript `undefined` has no Python value. Absent user sections, absent
  schema members, and explicit `undefined` entries in a write input all read as
  the port's undefined sentinel (`dsh.cordis.utils._UNDEFINED`), which keeps
  them distinct from a stored JSON `null`.
* The reference freezes every handed-out resolved value with `Object.freeze`;
  Python containers cannot be frozen, so `deep_freeze` returns a detached copy
  and a caller mutation reaches neither the stored document nor a later read.
* The reference's write queue, watcher chains, and listener containment are
  promise chains. Python schedules them on the running event loop when one
  exists; a caller outside any event loop has no microtask queue to cross
  (`dsh/cordis/fiber.py` documents the same adaptation for plugin loads), so
  the write runs inline and its failure raises at the call instead of settling
  a rejection nobody can observe.
"""

import asyncio
import copy
import inspect
import json
import math
from typing import Any, Callable, Dict, List, Optional, Set

from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED
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
    """A write refused because the namespace moved since the caller read it."""

    code = "SETTINGS_CONFLICT"

    def __init__(self, ns: str, expected: int, actual: int):
        super().__init__(
            f'settings namespace "{ns}" changed since it was read (expected revision {expected}, now {actual})'
        )
        self.name = "SettingsConflictError"
        self.ns = ns
        self.expected = expected
        self.actual = actual


def deep_equal_json(a: Any, b: Any) -> bool:
    """
    Deep structural equality over JSON-compatible data, the seam's single
    change-detection predicate.

    :param a: one JSON-compatible value.
    :param b: the other JSON-compatible value.
    :returns: whether the two values are structurally equal.
    """
    if a is b:
        return True
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        if isinstance(a, list) or isinstance(b, list):
            if not isinstance(a, list) or not isinstance(b, list):
                return False
            if len(a) != len(b):
                return False
            return all(deep_equal_json(x, y) for x, y in zip(a, b))
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        if len(a) != len(b):
            return False
        return all(key in b and deep_equal_json(value, b[key]) for key, value in a.items())
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        # ECMAScript strict equality keeps `true` and `1` apart.
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    # Functions, symbols, and the port's undefined sentinel compare by identity.
    return False


def is_plain_object(value: Any) -> bool:
    """Whether a value is a plain data object (not an array, null, or class instance)."""
    return isinstance(value, dict) and type(value) is dict


def apply_path_op(section: Dict[str, Any], op: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply one path op to a detached section, returning the next section.

    :param section: the section as it stands at the front of the write queue.
    :param op: `{op: 'set'|'unset', path: List[str]}` plus `value` for `set`.
    :returns: the next section; the empty path addresses the section itself.
    """
    head = op.get("path")[0] if op.get("path") else _UNDEFINED
    rest = list(op.get("path") or [])[1:]
    if head is _UNDEFINED or head is None:
        if op.get("op") == "unset":
            return {}
        value = op.get("value")
        if not is_plain_object(value):
            raise TypeError("settings mutate: setting the section root requires a plain object")
        return {key: entry for key, entry in value.items()}
    if not rest:
        if op.get("op") == "set":
            kept = {key: entry for key, entry in section.items()}
            kept[head] = op.get("value")
            return kept
        return {key: entry for key, entry in section.items() if key != head}
    child = section.get(head)
    if not is_plain_object(child):
        # Unsetting through an absent path is already satisfied; setting through
        # one creates the intermediate objects it needs.
        if op.get("op") == "unset":
            return section
        nested = apply_path_op({}, {"op": op.get("op"), "path": rest, "value": op.get("value")})
        kept = {key: entry for key, entry in section.items()}
        kept[head] = nested
        return kept
    kept = {key: entry for key, entry in section.items()}
    kept[head] = apply_path_op(child, {"op": op.get("op"), "path": rest, "value": op.get("value")})
    return kept


def describe_rejected(value: Any) -> str:
    """
    Human label for a value that lossless JSON cannot represent.

    JavaScript type names differ from the Python types the port validates, so
    the label names the Python type (`a datetime`, `a set`) where the reference
    would name its own (`a Date`, `a Set`).
    """
    if value is _UNDEFINED:
        return "undefined"
    if value is None:
        return "a object"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, type) or callable(value):
        return "a function"
    value_type = type(value)
    if value_type is dict or value_type is object:
        return "a non-plain object"
    return f"a {value_type.__name__}"


def clone_json_shaped(root: Dict[str, Any], reject: Callable[[str, str], TypeError]) -> Dict[str, Any]:
    """
    Detach and validate one write input in a single walk before persistence:
    only JSON data (plain objects, arrays, strings, finite numbers, booleans,
    `None`) may reach a provider document. `undefined` entries in objects are
    skipped (sparse-patch semantics), while an `undefined` array entry is
    rejected rather than coerced.

    :param root: plain-object write input (caller-checked).
    :param reject: builds the validation error from a value label and its `$`-rooted path.
    :returns: the detached JSON-compatible clone.
    """
    visiting: Set[int] = set()

    def _clone(value: Any, path: str) -> Any:
        if value is _UNDEFINED:
            raise reject("undefined", path)
        if value is None or isinstance(value, (str, bool)):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise reject("a non-finite number", path)
            return value
        if isinstance(value, list):
            if id(value) in visiting:
                raise reject("a circular reference", path)
            visiting.add(id(value))
            try:
                return [_clone(entry, f"{path}[{index}]") for index, entry in enumerate(value)]
            finally:
                # Un-mark on exit so one object referenced twice without a cycle passes.
                visiting.discard(id(value))
        if is_plain_object(value):
            if id(value) in visiting:
                raise reject("a circular reference", path)
            visiting.add(id(value))
            try:
                out: Dict[str, Any] = {}
                for key, entry in value.items():
                    if entry is _UNDEFINED:
                        continue
                    out[str(key)] = _clone(entry, f"{path}.{key}")
                return out
            finally:
                visiting.discard(id(value))
        raise reject(describe_rejected(value), path)

    return _clone(root, "$")


def merge_layers(under: Any, over: Any) -> Any:
    """
    Layer `over` onto `under`: plain objects merge recursively, every other
    value (lists included) replaces the lower layer wholesale.

    :param under: the lower layer, or the undefined sentinel when absent.
    :param over: the upper layer; the undefined sentinel keeps `under`.
    :returns: the merged layer.
    """
    if over is _UNDEFINED:
        return under
    if not is_plain_object(under) or not is_plain_object(over):
        return over
    merged: Dict[str, Any] = {key: entry for key, entry in under.items()}
    for key, value in over.items():
        merged[key] = merge_layers(merged[key], value) if key in merged else value
    return merged


def deep_freeze(value: Any) -> Any:
    """
    Detach one resolved value so handed-out snapshots stay stable.

    The reference freezes with `Object.freeze`; Python containers cannot be
    frozen, so this returns a copy no caller aliases.

    :param value: the resolved value to detach.
    :returns: the detached copy.
    """
    return copy.deepcopy(value)


def _running_loop() -> Optional[Any]:
    """The running event loop, or `None` for a caller outside one."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _consume_task(task: Any) -> None:
    """Retrieve a detached task's exception so the loop does not report it unretrieved."""
    if not task.cancelled():
        task.exception()


async def _await_result(awaitable: Any) -> None:
    """Drive one awaitable a loop-less caller cannot defer, so its failure is raised here."""
    await awaitable


class _SettledAwaitable:
    """
    An already-settled awaitable standing in for the promise a loop-less caller
    cannot schedule (see the module header).
    """

    def __await__(self) -> Any:
        if False:  # pragma: no cover - makes this function a generator
            yield None
        return None


class SettingsWatcher:
    """One registered watcher and its serialized invocation chain."""

    def __init__(self, callback: Callable[..., Any]):
        self.callback = callback
        self.tail: Optional[Any] = None
        self.active = True


class SettingsRegistration:
    """One live namespace registration owned by a registrant fiber."""

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
        self.revision: int = 0
        self.watchers: Set[SettingsWatcher] = set()


class SettingsScope:
    """Owner-facing handle for one registered namespace."""

    def __init__(self, provider: "SettingsProvider", registration: SettingsRegistration):
        self._provider = provider
        self._registration = registration

    def get(self) -> Any:
        """Current resolved value: schema defaults, then `base`, then the user layer."""
        return deep_freeze(self._registration.resolved)

    def watch(self, callback: Callable[..., Any]) -> Callable[[], None]:
        """
        Observe committed changes to this namespace's resolved value.

        :param callback: invoked after each commit with the next and previous values.
        :returns: the disposer removing this observer.
        """
        return self._provider.watch_scope(self._registration, callback)

    def update(self, patch: Dict[str, Any]) -> Any:
        """Merge a partial patch into this namespace's user layer and persist it."""
        return self._provider.update(self._registration.ns, patch)

    def replace(self, section: Dict[str, Any]) -> Any:
        """Replace this namespace's user section wholesale; absent keys re-inherit."""
        return self._provider.replace(self._registration.ns, section)


class SettingsProvider(Service):
    """
    Abstract settings service. Providers implement raw-document storage
    (`load`/`_persist_section`) and push external changes through `publish`;
    this class owns namespace registration, resolution, validation, change
    detection, revision tracking, and the commit events.
    """

    def __init__(self, ctx: Optional[Any] = None):
        super().__init__(ctx, "settings", allow_replace=True)
        self._registrations: Dict[str, SettingsRegistration] = {}
        self._document: Dict[str, Any] = {}
        self._write_queues: Dict[str, Any] = {}
        self._pending_tails: Set[Any] = set()
        self._stopped: bool = False

    async def init(self) -> Any:
        """
        Load the provider's document once and publish it before the service
        becomes injectable, and register the write-drain teardown.

        Providers with their own init (watchers, connections) delegate here.
        """
        yield self._drain_and_stop
        result = self.load()
        if inspect.isawaitable(result):
            result = await result
        self.publish(result)

    async def _drain_and_stop(self) -> None:
        """
        Teardown: refuse new writes and new watcher starts, then wait until
        every queued write chain and every started watcher invocation settles
        so disposal completes only once storage and observers are quiescent.
        """
        self._stopped = True
        pending = [task for task in list(self._write_queues.values()) + list(self._pending_tails)]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)

    @property
    def writable(self) -> bool:
        """Whether `update` may persist through this provider."""
        return True

    @property
    def document_path(self) -> Optional[str]:
        """Absolute path of the provider's user-editable document, when its storage is one local file."""
        return None

    def prepare_document(self) -> Optional[str]:
        """
        Prepare the provider's user-editable document for a native editor.

        :returns: the absolute local document path, or `None` for non-file storage.
        """
        return self.document_path

    def load(self) -> Any:
        """
        Read the provider's current raw document (namespace to raw section).

        :returns: the detached raw document.
        """
        legacy_load = getattr(self, "_load_document", None)
        if callable(legacy_load):
            return legacy_load()
        raise NotImplementedError

    def _persist_section(self, ns: str, section: Dict[str, Any]) -> None:
        """
        Durably store one namespace's merged user section.

        :param ns: the namespace being written.
        :param section: the complete merged user section to store.
        """
        raise NotImplementedError

    def register(
        self,
        ns: str,
        schema: Any = None,
        options: Optional[Dict[str, Any]] = None,
        base: Optional[Any] = None,
        applies: Optional[str] = None,
        validate: Optional[Callable[[Any], None]] = None,
    ) -> SettingsScope:
        """
        Register a namespace schema and receive its owner scope.

        The registration is an effect on the calling plugin's fiber: disposing
        that fiber removes the namespace and its observers. An invalid stored
        section fails the registration itself, the earliest point where the
        schema can judge it.

        :param ns: unique namespace; duplicate registration fails loud.
        :param schema: schemastery schema resolving this namespace's value.
        :param options: the reference's registration options (`base`, `applies`, `validate`).
        :param base: composition-layer values resolved below the user layer.
        :param applies: owner's effect timing, `live` or `restart`.
        :param validate: owner-supplied check for constraints the schema cannot express.
        :returns: the owner scope for reads, observation, and updates.
        """
        if options is not None:
            if not isinstance(options, dict):
                raise TypeError(f'settings register for "{ns}" options must be a plain object')
            if base is None:
                base = options.get("base")
            if applies is None:
                applies = options.get("applies")
            if validate is None:
                validate = options.get("validate")

        validated_ns = settings_namespace(ns)
        if validated_ns in self._registrations:
            raise ValueError(f'settings namespace "{validated_ns}" is already registered')

        registration = SettingsRegistration(
            ns=validated_ns,
            schema=schema,
            base=base,
            applies=applies if applies is not None else "live",
            validate=validate,
        )
        registration.resolved = deep_freeze(
            self._resolve(schema, base, self._get_section(validated_ns), validate)
        )

        if self.ctx is not None and getattr(self.ctx, "fiber", None) is not None:
            def _setup() -> Callable[[], Any]:
                self._registrations[validated_ns] = registration
                return lambda: self._registrations.pop(validated_ns, None)

            self.ctx.effect(_setup, f"settings.register({json.dumps(str(validated_ns))})")
        else:
            # A context without a fiber (a bare `Context()` used as a provider
            # host) cannot own an effect; the registration then lives until the
            # service is discarded.
            self._registrations[validated_ns] = registration

        return SettingsScope(self, registration)

    def describe(self, options: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Describe every registered namespace for configuration surfaces,
        including the composition `base` and raw user layers so a form can mark
        which fields the user overrode and what a reset returns to.

        :param options: redaction switch; wire surfaces must redact.
        :returns: one descriptor per registered namespace, in registration order.
        """
        redact = bool(options.get("redactSecrets")) if options else False
        descriptors: List[Dict[str, Any]] = []

        for registration in self._registrations.values():
            try:
                section = self._get_section(registration.ns)
            except TypeError:
                # A malformed stored section already warned at publish and kept
                # the last good resolved value; only that malformed value can
                # throw here, and describing it as "no user layer" keeps this
                # read total.
                section = _UNDEFINED
            detached_user = _UNDEFINED if section is _UNDEFINED else copy.deepcopy(section)
            detached_base = _UNDEFINED if registration.base is None else copy.deepcopy(registration.base)

            descriptor: Dict[str, Any] = {
                "ns": registration.ns,
                "schema": _serialized_schema(registration.schema),
                "value": deep_freeze(registration.resolved),
                "revision": registration.revision,
                "applies": registration.applies,
            }
            if detached_base is not _UNDEFINED:
                descriptor["base"] = detached_base
            if detached_user is not _UNDEFINED:
                descriptor["user"] = detached_user
            if not redact:
                descriptors.append(descriptor)
                continue

            schema = registration.schema
            redacted = redact_secrets(schema, registration.resolved)
            descriptor["value"] = redacted.value
            if detached_base is not _UNDEFINED:
                descriptor["base"] = redact_secrets(schema, detached_base).value
            if detached_user is not _UNDEFINED:
                descriptor["user"] = redact_secrets(schema, detached_user).value
            descriptor["secrets"] = [secret.to_dict() for secret in redacted.secrets]
            descriptors.append(descriptor)

        return descriptors

    def get(self, ns: str) -> Any:
        """
        Read one registered namespace's resolved value.

        :param ns: the namespace to read.
        :returns: the resolved value, or `None` while unregistered.
        """
        registration = self._registrations.get(ns)
        return None if registration is None else deep_freeze(registration.resolved)

    def watch_scope(self, registration: SettingsRegistration, callback: Callable[..., Any]) -> Callable[[], None]:
        """
        Observe one registration's committed changes.

        :param registration: the registration whose commits are observed.
        :param callback: invoked after each commit with the next and previous values.
        :returns: the disposer removing this observer.
        """
        watcher = SettingsWatcher(callback)
        registration.watchers.add(watcher)

        def dispose() -> None:
            watcher.active = False
            registration.watchers.discard(watcher)

        return dispose

    def update(self, ns: str, patch: Dict[str, Any], expected_revision: Optional[int] = None) -> Any:
        """
        Merge a patch into one registered namespace's user layer, validate the
        resolved candidate, persist through the provider, then commit and emit.

        :param ns: the registered namespace to update.
        :param patch: plain-object patch over the user section.
        :param expected_revision: the descriptor `revision` the caller read; a
            namespace that moved past it rejects with `SettingsConflictError`.
        :returns: an awaitable settling when the write reached storage.
        """
        return self._write(ns, patch, "merge", expected_revision)

    def replace(self, ns: str, section: Dict[str, Any], expected_revision: Optional[int] = None) -> Any:
        """
        Replace one registered namespace's user section wholesale, validate,
        persist, then commit and emit. Keys absent from `section` fall back to
        the composition `base` and schema defaults.

        :param ns: the registered namespace to replace.
        :param section: the complete next user section.
        :param expected_revision: the descriptor `revision` the caller read; a
            namespace that moved past it rejects with `SettingsConflictError`.
        :returns: an awaitable settling when the write reached storage.
        """
        return self._write(ns, section, "replace", expected_revision)

    def mutate(self, ns: str, ops: List[Dict[str, Any]], expected_revision: Optional[int] = None) -> Any:
        """
        Apply path-addressed edits to one registered namespace's user section,
        validate, persist, then commit and emit. The ops are applied to the
        section as it stands when the write reaches the front of the queue.

        :param ns: the registered namespace to edit.
        :param ops: ordered path edits; later ops observe earlier ones.
        :param expected_revision: the descriptor `revision` the caller read; a
            namespace that moved past it rejects with `SettingsConflictError`.
        :returns: an awaitable settling when the write reached storage.
        """
        if not isinstance(ops, list):
            raise TypeError(f'settings mutate for "{ns}" must be a list of path ops')
        for op in ops:
            if not is_plain_object(op) or op.get("op") not in ("set", "unset"):
                raise TypeError(f'settings mutate for "{ns}" ops must be {{op:\'set\'|\'unset\', path}}')
            path = op.get("path")
            if not isinstance(path, list) or any(not isinstance(part, str) for part in path):
                raise TypeError(f'settings mutate for "{ns}" op paths must be lists of strings')
        return self._write(ns, ops, "mutate", expected_revision)

    def _write(self, ns: str, input_data: Any, mode: str, expected_revision: Optional[int] = None) -> Any:
        """Validate a write, then queue it on the namespace's serialized write chain."""
        registration, verb, snapshot = self._prepare_write(ns, input_data, mode)

        loop = _running_loop()
        if loop is None:
            # A caller outside any event loop has no microtask queue to defer
            # the body onto (see the module header), so the write runs inline;
            # a provider that persists asynchronously is driven to completion
            # here because its rejection has no other observer.
            settled = self._execute_write(ns, registration, mode, verb, snapshot, expected_revision)
            if inspect.isawaitable(settled):
                asyncio.run(_await_result(settled))
            return _SettledAwaitable()

        previous = self._write_queues.get(ns)
        task = loop.create_task(
            self._queued_write(previous, ns, registration, mode, verb, snapshot, expected_revision)
        )
        self._write_queues[ns] = task
        task.add_done_callback(_consume_task)
        return task

    def _prepare_write(self, ns: str, input_data: Any, mode: str) -> Any:
        """
        Validate one write input and detach it, before it is queued.

        :param ns: the registered namespace to write.
        :param input_data: the patch, section, or path-op list.
        :param mode: `merge`, `replace`, or `mutate`.
        :returns: the registration, the write's verb, and the detached snapshot.
        """
        verb = "update" if mode == "merge" else ("replace" if mode == "replace" else "mutate")
        registration = self._registrations.get(ns)
        if registration is None:
            raise ValueError(f'settings namespace "{ns}" is not registered')
        if self._stopped:
            raise RuntimeError(f'settings service is disposed: "{ns}" cannot be written')
        if not self.writable:
            raise RuntimeError(f'settings provider is read-only: "{ns}" cannot be updated in-process')

        # A mutate's ops array is wrapped so one JSON-shape walk covers both
        # shapes; merge/replace carry the section itself.
        if mode == "mutate":
            payload: Dict[str, Any] = {"ops": input_data}
        else:
            if not is_plain_object(input_data):
                raise TypeError(f'settings {verb} for "{ns}" must be a plain object')
            payload = input_data

        # Snapshot at call time: the queue must never read a caller-owned object
        # the caller may keep mutating while the write waits its turn. The same
        # walk rejects values that JSON cannot preserve (see clone_json_shaped).
        snapshot = clone_json_shaped(
            payload,
            lambda label, path: TypeError(
                f'settings {verb} for "{ns}" must contain only JSON-compatible data (found {label} at {path})'
            ),
        )
        return registration, verb, snapshot

    async def _queued_write(
        self,
        previous: Any,
        ns: str,
        registration: SettingsRegistration,
        mode: str,
        verb: str,
        snapshot: Dict[str, Any],
        expected_revision: Optional[int],
    ) -> None:
        """One queued write segment: wait out its predecessor, then apply the write."""
        if previous is not None:
            try:
                # Chain past a failed predecessor: one rejected write must not
                # poison the namespace queue for every later caller.
                await previous
            except BaseException:
                pass
        settled = self._execute_write(ns, registration, mode, verb, snapshot, expected_revision)
        if inspect.isawaitable(settled):
            await settled

    def _execute_write(
        self,
        ns: str,
        registration: SettingsRegistration,
        mode: str,
        verb: str,
        snapshot: Dict[str, Any],
        expected_revision: Optional[int],
    ) -> Any:
        """
        Apply one write at the front of its namespace's queue.

        :returns: an awaitable when the provider persists asynchronously, else `None`.
        """
        if self._stopped:
            raise RuntimeError(f'settings service was disposed before the queued "{ns}" {verb} ran')
        if self._registrations.get(ns) is not registration:
            raise RuntimeError(
                f'settings namespace "{ns}" registration was disposed before the queued {verb} ran'
            )
        # Every mode derives from the section as it stands NOW, at the front of
        # the queue, never from whatever the caller last saw.
        current = self._get_section(ns)
        if current is _UNDEFINED:
            current = {}
        # The revision check belongs HERE, not at call time: the queue orders
        # writes but cannot tell a fresh writer from one holding a snapshot
        # that a predecessor already superseded.
        if expected_revision is not None and expected_revision != registration.revision:
            raise SettingsConflictError(ns, expected_revision, registration.revision)

        if mode == "merge":
            section = merge_layers(current, snapshot)
        elif mode == "replace":
            section = snapshot
        else:
            section = current
            for op in snapshot.get("ops") or []:
                section = apply_path_op(section, op)

        next_resolved = deep_freeze(
            self._resolve(registration.schema, registration.base, section, registration.validate)
        )
        persisted = self._persist_section(ns, section)
        if inspect.isawaitable(persisted):
            async def _settle() -> None:
                await persisted
                self._commit_write(ns, registration, current, section, next_resolved)

            return _settle()
        self._commit_write(ns, registration, current, section, next_resolved)
        return None

    def _commit_write(
        self,
        ns: str,
        registration: SettingsRegistration,
        current: Dict[str, Any],
        section: Dict[str, Any],
        next_resolved: Any,
    ) -> None:
        """
        Record one persisted write. The write reached storage either way, so
        the cache must say so; commit only when this registration is still the
        namespace owner, because a fiber disposed (or replaced) mid-persist
        must not receive the notification.
        """
        self._document[ns] = section
        if self._registrations.get(ns) is registration and not self._stopped:
            self.bump_revision(registration, current, section)
            self.commit(registration, next_resolved, "update")

    def publish(self, doc: Dict[str, Any], source: str = "provider") -> None:
        """
        Provider hook: commit a complete raw document observed in storage. Each
        registered namespace re-resolves; an invalid section keeps that
        namespace's last good value and warns, other namespaces still commit.

        :param doc: the detached raw document (unregistered sections preserved).
        :param source: change origin.
        """
        # Read every raw section BEFORE swapping the document, so the revision
        # bump below compares what was stored with what now is.
        before: Dict[str, Any] = {}
        for registration in list(self._registrations.values()):
            try:
                before[registration.ns] = self._get_section(registration.ns)
            except TypeError:
                # A malformed stored section is not a readable "before";
                # treating it as absent still bumps against any replacement.
                before[registration.ns] = _UNDEFINED

        # The document is mutated in place instead of rebound: a provider read
        # through a derived context (`getTraceable`) would otherwise shadow the
        # attribute on that derived object and leave every other reader on the
        # previous document.
        detached = copy.deepcopy(doc)
        self._document.clear()
        self._document.update(detached)

        for registration in list(self._registrations.values()):
            try:
                section = self._get_section(registration.ns)
                next_resolved = deep_freeze(
                    self._resolve(registration.schema, registration.base, section, registration.validate)
                )
            except Exception as error:
                self._log("warn", 'settings: keeping last good "%s" after invalid stored section', registration.ns)
                self._log("warn", error)
                continue
            self.bump_revision(registration, before.get(registration.ns), section)
            self.commit(registration, next_resolved, source)

    def _get_section(self, ns: str) -> Any:
        """Read one namespace's raw user section, rejecting non-object sections."""
        section = self._document.get(ns, _UNDEFINED)
        if section is _UNDEFINED:
            return _UNDEFINED
        if not is_plain_object(section):
            raise TypeError(f'settings section "{ns}" must be an object of keys')
        return section

    def _resolve(
        self,
        schema: Any,
        base: Any,
        section: Any,
        validate: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        """Resolve one namespace value: schema defaults, then `base`, then the user layer."""
        merged = merge_layers(_UNDEFINED if base is None else base, section)
        if schema is None:
            value = merged
        elif callable(schema):
            value = schema(merged)
        elif hasattr(schema, "parse"):
            value = schema.parse(merged)
        elif hasattr(schema, "evaluate"):
            value = schema.evaluate(merged)
        else:
            value = merged
        # The owner's own check runs on the admitted value, so it sees defaults
        # and the composition base exactly as the owner will.
        if validate is not None:
            validate(value)
        return value

    def bump_revision(self, registration: SettingsRegistration, before: Any, after: Any) -> None:
        """
        Advance a namespace's revision when its RAW section changed, and
        announce it. Independent of `commit`'s resolved-value equality: storing
        an override equal to the composition base leaves the resolved value
        alone but changes what the document says.
        """
        if deep_equal_json(before, after):
            return
        registration.revision += 1
        self._emit_document_updated(registration.ns, registration.revision)

    def _emit_document_updated(self, ns: str, revision: int) -> None:
        """Contained fan-out of `settings/document-updated`, mirroring `commit`'s."""
        self._fan_out(
            "settings/document-updated",
            [ns, revision],
            lambda error: self._warn_listener_failure(ns, error),
        )

    def commit(self, registration: SettingsRegistration, next_val: Any, source: str) -> None:
        """Commit a resolved value when changed: swap, notify watchers, emit the event."""
        prev_val = registration.resolved
        if deep_equal_json(next_val, prev_val):
            return
        registration.resolved = next_val

        # Observers receive detached snapshots: the reference hands out the
        # frozen value, and a detached copy is the port's equivalent of an
        # observer that cannot reach the committed state.
        notified_next = deep_freeze(next_val)
        notified_prev = deep_freeze(prev_val)
        for watcher in list(registration.watchers):
            self._invoke_watcher(registration, watcher, notified_next, notified_prev)

        self._fan_out(
            "settings/updated",
            [registration.ns, notified_next, notified_prev, source],
            lambda error: self._warn_listener_failure(registration.ns, error),
        )

    def _fan_out(self, event_name: str, event_args: List[Any], warn: Callable[[Exception], None]) -> None:
        """
        Fan one event out to every listener, one at a time: the plain emit stops
        at the first throwing listener. `INVARIANT`-coded failures are
        harness-fatal by design and rethrow after every listener ran; any other
        failure is contained so one broken observer cannot wedge the commit
        path (and, through it, a provider's reload loop).
        """
        events = getattr(self.ctx, "events", None) if self.ctx is not None else None
        if events is None:
            return
        listeners = events.dispatch("emit", [event_name] + list(event_args))
        invariant_failure: Optional[Exception] = None
        for listener in listeners:
            try:
                returned = listener(*event_args)
                if inspect.isawaitable(returned):
                    # An emit listener may still be an async function; its
                    # rejection cannot reach the synchronous INVARIANT rethrow
                    # below, so it is contained here instead of becoming an
                    # unhandled rejection.
                    self._contain_awaitable(returned, warn)
            except Exception as error:
                if getattr(error, "code", None) == "INVARIANT":
                    if invariant_failure is None:
                        invariant_failure = error
                    continue
                warn(error)
        if invariant_failure is not None:
            raise invariant_failure

    def _contain_awaitable(self, awaitable: Any, warn: Callable[[Exception], None]) -> None:
        """Await one listener/watcher result, containing its rejection."""

        async def _guarded() -> None:
            try:
                await awaitable
            except Exception as error:
                warn(error)

        loop = _running_loop()
        if loop is None:
            asyncio.run(_guarded())
            return
        task = loop.create_task(_guarded())
        task.add_done_callback(_consume_task)

    def _invoke_watcher(
        self,
        registration: SettingsRegistration,
        watcher: SettingsWatcher,
        next_val: Any,
        prev_val: Any,
    ) -> None:
        """
        Start one watcher invocation.

        Invocations of one callback run one at a time in commit order, so a
        slow stale invocation can never apply after a newer one. The activity
        check runs when the queued invocation would start, so a disposer (or
        service stop) that ran while it waited prevents the start entirely;
        started invocations drain at service dispose.
        """
        loop = _running_loop()
        if loop is None:
            guarded = self._call_watcher(registration, watcher, next_val, prev_val)
            if guarded is not None:
                asyncio.run(_await_result(guarded))
            return
        previous = watcher.tail

        async def _segment() -> None:
            if previous is not None:
                try:
                    await previous
                except BaseException:
                    pass
            guarded = self._call_watcher(registration, watcher, next_val, prev_val)
            if guarded is not None:
                await guarded

        task = loop.create_task(_segment())
        watcher.tail = task
        self._pending_tails.add(task)

        def _settle(settled: Any, watcher: SettingsWatcher = watcher) -> None:
            self._pending_tails.discard(settled)
            _consume_task(settled)

        task.add_done_callback(_settle)

    def _call_watcher(
        self,
        registration: SettingsRegistration,
        watcher: SettingsWatcher,
        next_val: Any,
        prev_val: Any,
    ) -> Any:
        """
        Invoke one watcher callback.

        The activity check runs when the invocation starts, so a disposer (or
        service stop) that ran while it waited prevents the start entirely.

        :returns: the awaitable guarding an async callback's rejection, else `None`.
        """
        if not watcher.active or self._stopped:
            return None
        try:
            returned = watcher.callback(next_val, prev_val)
        except Exception as error:
            self._warn_watcher_failure(registration.ns, error)
            return None
        if inspect.isawaitable(returned):
            return self._guard_watcher(registration, returned)
        return None

    async def _guard_watcher(self, registration: SettingsRegistration, awaitable: Any) -> None:
        """Await one watcher callback, containing its rejection."""
        try:
            await awaitable
        except Exception as error:
            self._warn_watcher_failure(registration.ns, error)

    def _warn_watcher_failure(self, ns: str, error: Any) -> None:
        """Contained-watcher diagnostic shared by the sync and async failure paths."""
        self._log("warn", 'settings: watcher for "%s" failed', ns)
        self._log("warn", error)

    def _warn_listener_failure(self, ns: str, error: Any) -> None:
        """Contained-listener diagnostic shared by the sync and async failure paths."""
        self._log("warn", 'settings: a settings/updated listener for "%s" failed', ns)
        self._log("warn", error)

    def _log(self, level: str, message: Any, *args: Any) -> None:
        logger = getattr(self.ctx, "logger", None) if self.ctx is not None else None
        if logger is None:
            return
        try:
            getattr(logger, level)(message, *args)
        except Exception:
            # A logger that cannot take the level is not a settings failure.
            pass


def _serialized_schema(schema: Any) -> Any:
    """
    Serialize one registered schema through the reference's canonical wire
    form: `schema.toJSON()`, a `{ uid, refs }` envelope `new Schema(json)` can
    rehydrate.

    :param schema: the schema a registration carries.
    :returns: the serialized envelope, or the schema itself when it is not a
        schemastery node (the port admits a plain mapping as a schema).
    """
    to_json = getattr(schema, "toJSON", None)
    if callable(to_json):
        return to_json()
    return copy.deepcopy(schema)


def install_settings_section(
    ctx: Any,
    ns: str,
    schema: Any,
    entry: Any,
    hooks: Dict[str, Any],
) -> None:
    """
    Install the canonical optional-settings consumer wiring: while a settings
    service exists, register `ns` with the consumer's composition entry as the
    `base` layer and point the source thunk at the resolved scope; when the
    service goes away, fall back to the entry so the consumer keeps working
    exactly as composed.

    Hooks dictionary must contain:
    - 'setSource': Callable[[Callable[[], T]], None]
    - 'onChange': Callable[[], None]
    - 'validate': Optional[Callable[[T], None]]

    :param ctx: consumer plugin context owning the wiring.
    :param ns: the consumer-owned settings namespace.
    :param schema: schema resolving the namespace (typically the plugin Config).
    :param entry: the consumer's composition entry config, used as `base`.
    :param hooks: source sink and change notification.
    """
    def _mount(sctx: Any):
        settings_svc = sctx.get("settings") if hasattr(sctx, "get") else None
        if not settings_svc:
            return
        options: Dict[str, Any] = {"base": entry}
        if hooks.get("validate") is not None:
            options["validate"] = hooks["validate"]
        scope = settings_svc.register(ns, schema, options)
        hooks["setSource"](lambda: scope.get())

        def _disposer() -> None:
            # This disposer runs for two different reasons. A settings provider
            # detaching leaves the consumer running, so it must fall back to
            # its composition entry and re-judge what it derived. The
            # consumer's own unload runs it too, and there `onChange` would
            # re-register routes and touch resources the teardown is releasing,
            # so the fallback is pointless and the notification actively
            # harmful.
            if _is_unloading(ctx):
                return
            hooks["setSource"](lambda: entry)
            hooks["onChange"]()

        sctx.effect(lambda: _disposer, f"installSettingsSection({ns})")
        hooks["onChange"]()
        scope.watch(lambda _next, _prev: None if _is_unloading(ctx) else hooks["onChange"]())

    ctx.inject(["settings"], _mount)


def _is_unloading(ctx: Any) -> bool:
    """Whether the consumer's own fiber is tearing down (not just losing the settings service)."""
    from dsh.cordis.fiber import FiberState

    fiber = getattr(ctx, "fiber", None)
    if fiber is None:
        return False
    return fiber.state in (FiberState.UNLOADING, FiberState.DISPOSED)
