"""Stable config references carrying detached, immutable JSON snapshots."""
from typing import Any, Dict, Generic, List, Set, TypeVar

WRITE = 'cosmokit.volatile.write'
T = TypeVar('T')


def _immutable(*args: Any, **kwargs: Any) -> None:
    raise TypeError('volatile config snapshot is immutable')


class _FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable


class _FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable


def _snapshot(value: Any, ancestors: Set[int]) -> Any:
    from dsh.cordis.utils import _UNDEFINED, _js_own_enumerable_keys
    if callable(value):raise TypeError('volatile config cannot contain functions')
    if isinstance(value,Volatile):raise TypeError('volatile config cannot contain functions')
    if value is _UNDEFINED or value is None or isinstance(value, (str, bool, int, float)):
        return value
    identity=id(value)
    if identity in ancestors:raise TypeError('volatile config cannot contain cycles')
    ancestors.add(identity)
    try:
        if isinstance(value, list):
            return _FrozenList(_snapshot(item, ancestors) for item in value)
        if not isinstance(value, dict):
            raise TypeError('volatile config objects must be plain objects or arrays')
        return _FrozenDict((key, _snapshot(value[key], ancestors)) for key in _js_own_enumerable_keys(value))
    finally:
        ancestors.remove(identity)


class Volatile(Generic[T]):
    __slots__ = ('_current',)

    def __init__(self, value: Any):
        object.__setattr__(self, '_current', _snapshot(value, set()))

    def get(self) -> T:
        return self._current

    def __setattr__(self, name: str, value: Any) -> None:
        _immutable()

    def __getattr__(self, name: str) -> Any:
        if name == WRITE:return self._write
        raise AttributeError(name)

    def _write(self, value: Any) -> None:
        object.__setattr__(self, '_current', value)


def create_volatile(value: Any) -> Volatile:
    return Volatile(value)


def is_volatile(value: Any) -> bool:
    return value is not None and hasattr(value, WRITE)


def volatile_entries(value: Any) -> List[Dict[str, Any]]:
    ancestors: Set[int] = set()
    def visit(item: Any, path: List[str]) -> List[Dict[str, Any]]:
        if is_volatile(item):return [{'path':path,'ref':item}]
        if not isinstance(item, (dict, list)) or id(item) in ancestors:return []
        ancestors.add(id(item))
        try:
            from dsh.cordis.utils import _js_own_enumerable_keys
            entries = enumerate(item) if isinstance(item,list) else ((key,item[key]) for key in _js_own_enumerable_keys(item))
            return [found for key,child in entries for found in visit(child,path+[str(key)])]
        finally:
            ancestors.remove(id(item))
    return visit(value,[])


def update_volatile(target: Any, source: Any) -> None:
    getattr(target, WRITE)(source.get())


createVolatile = create_volatile
isVolatile = is_volatile
volatileEntries = volatile_entries
updateVolatile = update_volatile
