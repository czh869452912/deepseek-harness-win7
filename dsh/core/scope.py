"""
Scoped-context primitive: mint a Cordis context that tags registrations with
an opaque identity and build routing-only event carriers for that identity.
1:1 aligned with official `@deepseek-ai/dsh-scope`.
"""

import weakref
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, TypeVar, Union
from dsh.cordis.context import Context

T = TypeVar("T")
V = TypeVar("V")

# Context attribute key written by create_scope
K_SCOPE = "_dsh_scope_key"

# Global weak maps tracking scope hierarchy and carriers
_scope_parents: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()
_carrier_keys: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()


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


def create_scope(ctx: Context, key: Any, parent: Optional[Any] = None) -> Scope:
    """
    Mint a scope under ctx. The scoped context inherits the minting context's
    dependency API and owns every registration made through it.
    """
    if parent is not None:
        bind_scope_parent(key, parent)

    scoped = ctx.extend()
    setattr(scoped, K_SCOPE, key)

    def raw_dispose():
        scoped.teardown()

    return Scope(ctx=scoped, raw_dispose=raw_dispose, fiber_dispose=raw_dispose)


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
        return iter(self.data.items())

    def is_empty(self) -> bool:
        return len(self.data) == 0


class AnonymousEntries:
    """Insertion-ordered anonymous entries."""

    def __init__(self):
        self.data: List[Any] = []

    def insert(self, value: Any) -> Callable[[], None]:
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

    def values(self) -> Iterator[Any]:
        return iter(self.data)

    def is_empty(self) -> bool:
        return len(self.data) == 0


class ScopedLayers:
    """Layers of tables partitioned by scope key."""

    def __init__(self, create_layer: Callable[[Any], Any]):
        self._create_layer = create_layer
        self._layers: Dict[Any, Any] = {}
        self._unscoped = create_layer(None)

    def layer_of(self, ctx_or_key: Any) -> Any:
        key = scope_of(ctx_or_key) if isinstance(ctx_or_key, Context) else ctx_or_key
        if key is None:
            return self._unscoped
        if key not in self._layers:
            self._layers[key] = self._create_layer(key)
        return self._layers[key]

    def chain_layers_of(self, ctx_or_key: Any) -> List[Any]:
        key = scope_of(ctx_or_key) if isinstance(ctx_or_key, Context) else ctx_or_key
        chain = scope_chain_of(key)
        layers = [self._layers[k] for k in chain if k in self._layers]
        layers.append(self._unscoped)
        return layers
