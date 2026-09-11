"""
Scoped-context primitive: mint a Cordis context that tags registrations with
an opaque identity and build routing-only event carriers for that identity.
1:1 aligned with official `@deepseek-ai/dsh-scope`.
"""

import collections.abc
import inspect
import weakref
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, TypeVar, Union
from dsh.cordis.context import Context

T = TypeVar("T")
V = TypeVar("V")

# Context attribute key written by create_scope
K_SCOPE = "_dsh_scope_key"


class ScopeKey:
    """Opaque hashable, weakrefable scope key matching JS object reference identity."""
    __slots__ = ("value", "__weakref__")

    def __init__(self, value: Any):
        self.value = value

    def __repr__(self) -> str:
        return f"ScopeKey({self.value!r})"

    def __getitem__(self, item: str) -> Any:
        if isinstance(self.value, dict):
            return self.value[item]
        return getattr(self.value, item)


class _UniversalKeyMap:
    """Key map supporting both weakrefable and non-weakrefable keys."""

    def __init__(self):
        self._weak: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()
        self._strong: Dict[Any, Any] = {}

    def __setitem__(self, key: Any, value: Any) -> None:
        try:
            self._weak[key] = value
        except TypeError:
            self._strong[key] = value

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self._weak.get(key, default)
        except TypeError:
            return self._strong.get(key, default)

    def __contains__(self, key: Any) -> bool:
        try:
            return key in self._weak
        except TypeError:
            return key in self._strong

    def pop(self, key: Any, default: Any = None) -> Any:
        try:
            return self._weak.pop(key, default)
        except TypeError:
            return self._strong.pop(key, default)


# Global weak/universal maps tracking scope hierarchy and carriers
_scope_parents: _UniversalKeyMap = _UniversalKeyMap()
_carrier_keys: _UniversalKeyMap = _UniversalKeyMap()


class ScopeParentBinding:
    """The privileged handle to move one scope key's parent link."""

    def __init__(self, key: Any):
        self._key = key

    def rebind(self, parent: Any) -> None:
        _link_scope_parent(self._key, parent)


def _link_scope_parent(key: Any, parent: Any) -> None:
    cursor = parent
    while cursor is not None:
        if cursor == key:
            raise ValueError("dsh-scope: scope parent link would form a cycle")
        cursor = _scope_parents.get(cursor)
    _scope_parents[key] = parent


def bind_scope_parent(key: Any, parent: Any) -> ScopeParentBinding:
    """
    Bind parent as key's enclosing scope, once.
    """
    if key in _scope_parents:
        raise ValueError(
            "dsh-scope: scope key is already bound to a parent; re-linking requires the binding returned by the original bind"
        )
    _link_scope_parent(key, parent)
    return ScopeParentBinding(key)


def scope_parent_of(key: Any) -> Optional[Any]:
    """Read one key's enclosing scope."""
    return _scope_parents.get(key)


def scope_chain_of(key: Optional[Any]) -> List[Any]:
    """The chain from a key to its root ancestor: [key, parent, grandparent, ...]."""
    chain: List[Any] = []
    cursor = key
    while cursor is not None:
        chain.append(cursor)
        cursor = _scope_parents.get(cursor)
    return chain


class Scope:
    """A minted registration scope and its disposal boundaries."""

    def __init__(self, ctx: Context, raw_dispose: Callable[[], Any], fiber_dispose: Callable[[], Any]):
        self.ctx = ctx
        self.raw_dispose = raw_dispose
        self._fiber_dispose = fiber_dispose

    async def dispose(self) -> None:
        res = self._fiber_dispose()
        if hasattr(res, "__await__"):
            await res


def _empty_scope_plugin(ctx: Context) -> None:
    pass


def create_scope(ctx: Context, key: Any, options_or_parent: Optional[Any] = None) -> Scope:
    """
    Mint a scope under ctx. The scoped context inherits the minting context's
    dependency API and owns every registration made through it.
    """
    parent = None
    if isinstance(options_or_parent, dict) and "parent" in options_or_parent:
        parent = options_or_parent["parent"]
    elif options_or_parent is not None and not isinstance(options_or_parent, dict):
        parent = options_or_parent

    if not isinstance(key, collections.abc.Hashable):
        key = ScopeKey(key)
    if parent is not None and not isinstance(parent, collections.abc.Hashable):
        parent = ScopeKey(parent)

    if parent is not None:
        bind_scope_parent(key, parent)

    fiber = ctx.plugin(_empty_scope_plugin)
    scoped = fiber.ctx.extend()
    setattr(scoped, K_SCOPE, key)

    async def dispose() -> None:
        res = fiber.dispose()
        if inspect.isawaitable(res):
            await res
        if hasattr(fiber, "inertia") and fiber.inertia is not None:
            if inspect.isawaitable(fiber.inertia):
                await fiber.inertia

    def raw_dispose() -> Any:
        return fiber.dispose()

    return Scope(ctx=scoped, raw_dispose=raw_dispose, fiber_dispose=dispose)


def scope_of(ctx: Context) -> Optional[Any]:
    """Read the nearest scope tag inherited by a context."""
    cursor: Optional[Any] = ctx
    while cursor is not None:
        val = getattr(cursor, K_SCOPE, None)
        if val is not None:
            return val
        cursor = getattr(cursor, "_parent", None) or getattr(cursor, "parent", None)
    return None


class ScopedCarrier:
    """Routing-only carrier created by scope_target."""

    def __init__(self, base: Any, key: Optional[Any]):
        self.base = base
        self.key = key

    def __call__(self, ctx: Context) -> bool:
        tag = scope_of(ctx)
        if tag is None:
            return True
        cursor = self.key
        while cursor is not None:
            if cursor == tag:
                return True
            cursor = _scope_parents.get(cursor)
        return False


def scope_target(base: Any, key: Optional[Any]) -> Any:
    """
    Build an opaque receiver that preserves the base filter, admits untagged listeners
    globally, and admits tagged listeners for a matching key or any of its ancestors.
    """
    carrier = ScopedCarrier(base, key)
    try:
        _carrier_keys[carrier] = key
    except TypeError:
        pass
    return carrier


def is_scope_carrier(value: Any) -> bool:
    """Test whether a value is a scope carrier."""
    return isinstance(value, ScopedCarrier) or value in _carrier_keys


def carrier_key_of(value: Any) -> Optional[Any]:
    """Read a carrier's routing key."""
    if isinstance(value, ScopedCarrier):
        return value.key
    return _carrier_keys.get(value)


class ScopeLayer:
    """One scope's aggregate contribution to a registry."""

    def is_empty(self) -> bool:
        return True

    isEmpty = is_empty


class NamedEntries:
    """Insertion-ordered named entries with caller-owned duplicate diagnostics."""

    def __init__(self, duplicate_error: Callable[[str], Exception]):
        self.duplicate_error = duplicate_error
        self.data: Dict[str, Any] = {}

    def insert(self, name: str, value: Any) -> Callable[[], None]:
        if name in self.data:
            raise self.duplicate_error(name)
        self.data[name] = value
        active = True

        def undo():
            nonlocal active
            if not active:
                return
            active = False
            self.data.pop(name, None)

        return undo

    def get(self, name: str) -> Optional[Any]:
        return self.data.get(name)

    def has(self, name: str) -> bool:
        return name in self.data

    def keys(self) -> Iterator[str]:
        return iter(self.data.keys())

    def values(self) -> Iterator[Any]:
        return iter(self.data.values())

    def entries(self) -> Iterator[Tuple[str, Any]]:
        keys = list(self.data.keys())
        idx = 0
        while idx < len(keys):
            k = keys[idx]
            idx += 1
            if k in self.data:
                yield k, self.data[k]
            for new_k in self.data.keys():
                if new_k not in keys:
                    keys.append(new_k)

    def is_empty(self) -> bool:
        return len(self.data) == 0


class AnonymousEntries:
    """Insertion-ordered anonymous entries."""

    def __init__(self):
        self.data: List[Any] = []

    def append(self, value: Any) -> Callable[[], None]:
        self.data.append(value)
        active = True

        def undo():
            nonlocal active
            if not active:
                return
            active = False
            if value in self.data:
                self.data.remove(value)

        return undo

    insert = append

    def values(self) -> Iterator[Any]:
        return iter(list(self.data))

    def is_empty(self) -> bool:
        return len(self.data) == 0

    isEmpty = is_empty


class ScopedLayers:
    """Layers of tables partitioned by scope key."""

    def __init__(self, create_layer: Callable[[Any], Any], on_change: Optional[Callable[[], None]] = None):
        self._create_layer = create_layer
        self._on_change = on_change or (lambda: None)
        self.scoped: Dict[Any, Any] = {}
        self._layers = self.scoped
        self.global_layer = create_layer(None)
        self._unscoped = self.global_layer

    @property
    def global_(self) -> Any:
        return self.global_layer

    def peek(self, scope: Optional[Any]) -> Optional[Any]:
        if scope is None:
            return None
        if not isinstance(scope, collections.abc.Hashable):
            scope = ScopeKey(scope)
        return self.scoped.get(scope)

    def chain_layers(self, scope: Optional[Any]) -> List[Any]:
        key = scope_of(scope) if isinstance(scope, Context) else scope
        if key is not None and not isinstance(key, collections.abc.Hashable):
            key = ScopeKey(key)
        layers: List[Any] = []
        for k in reversed(scope_chain_of(key)):
            if k in self.scoped:
                layers.append(self.scoped[k])
        return layers

    chainLayers = chain_layers

    def chain_layers_of(self, ctx_or_key: Any) -> List[Any]:
        key = scope_of(ctx_or_key) if isinstance(ctx_or_key, Context) else ctx_or_key
        if key is not None and not isinstance(key, collections.abc.Hashable):
            key = ScopeKey(key)
        chain = scope_chain_of(key)
        layers = [self.scoped[k] for k in chain if k in self.scoped]
        layers.append(self.global_layer)
        return layers

    def merge(self, scope: Optional[Any], pick: Callable[[Any], NamedEntries]) -> Dict[str, Any]:
        merged: Dict[str, Any] = dict(pick(self.global_layer).entries())
        for layer in self.chain_layers(scope):
            for name, value in pick(layer).entries():
                merged[name] = value
        return merged

    def layer_of(self, ctx_or_key: Any) -> Any:
        key = scope_of(ctx_or_key) if isinstance(ctx_or_key, Context) else ctx_or_key
        if key is None:
            return self.global_layer
        if not isinstance(key, collections.abc.Hashable):
            key = ScopeKey(key)
        if key not in self.scoped:
            self.scoped[key] = self._create_layer(key)
        return self.scoped[key]

    def effect(
        self,
        ctx: Context,
        action: Callable[[Any], Callable[[], None]],
        options: Optional[Dict[str, Any]] = None,
    ) -> Callable[[], None]:
        opts = options or {}
        label = opts.get("label", "scoped_layers.effect()")
        notify = opts.get("notify", True)
        scope = scope_of(ctx)
        if scope is not None and not isinstance(scope, collections.abc.Hashable):
            scope = ScopeKey(scope)

        layer: Any
        created = False
        if scope is None:
            layer = self.global_layer
        else:
            existing = self.scoped.get(scope)
            if existing is None:
                layer = self._create_layer(scope)
                self.scoped[scope] = layer
                created = True
            else:
                layer = existing

        try:
            undo = action(layer)
        except Exception as error:
            if scope is not None and created and hasattr(layer, "is_empty") and layer.is_empty():
                self.scoped.pop(scope, None)
            raise error

        def cleanup():
            undo()
            if scope is not None and hasattr(layer, "is_empty") and layer.is_empty():
                self.scoped.pop(scope, None)
            if notify:
                self._on_change()

        if notify:
            try:
                self._on_change()
            except Exception as error:
                undo()
                if scope is not None and created and hasattr(layer, "is_empty") and layer.is_empty():
                    self.scoped.pop(scope, None)
                raise error

        if hasattr(ctx, "effect"):
            return ctx.effect(lambda: cleanup, label=label)
        return cleanup
