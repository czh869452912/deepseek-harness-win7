"""
Lossless-JSON validation and detached snapshots for durable session data.
Ported 1:1 from reference packages/core/session/src/json.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import math
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class _UndefinedType:
    def __repr__(self) -> str:
        return "undefined"

    def __bool__(self) -> bool:
        return False


UNDEFINED = _UndefinedType()


class FrozenDict(dict):
    """
    Immutable mapping: the Python 3.8.10 equivalent of an `Object.freeze`d JSON
    object. Python cannot freeze an existing `dict` in place, so durability is
    emulated with a `dict` subclass whose mutators raise `TypeError` - the same
    error a strict-mode JavaScript write to a frozen object throws. Because it
    still IS a `dict`, `json.dumps`, equality, iteration, `isinstance` checks
    and the mapping protocol keep working on frozen durable session data.
    """

    __slots__ = ()

    def _frozen(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen session object does not support item assignment")

    __setitem__ = _frozen
    __delitem__ = _frozen
    clear = _frozen
    pop = _frozen
    popitem = _frozen
    setdefault = _frozen
    update = _frozen

    def __copy__(self) -> Dict[str, Any]:
        return dict(self)

    def __deepcopy__(self, memo: Any = None) -> Dict[str, Any]:
        # `copy.deepcopy` mirrors `structuredClone`: a copy is detached and no
        # longer frozen, exactly like the reference `snapshotSessionEvent`.
        return copy.deepcopy(dict(self), memo if memo is not None else {})

    def __reduce__(self) -> Any:
        return (FrozenDict, (dict(self),))


class FrozenList(list):
    """Immutable array: the Python equivalent of an `Object.freeze`d JSON array."""

    __slots__ = ()

    def _frozen(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen session array does not support item assignment")

    __setitem__ = _frozen
    __delitem__ = _frozen
    append = _frozen
    extend = _frozen
    insert = _frozen
    pop = _frozen
    remove = _frozen
    clear = _frozen
    reverse = _frozen
    sort = _frozen
    __iadd__ = _frozen
    __imul__ = _frozen

    def __copy__(self) -> List[Any]:
        return list(self)

    def __deepcopy__(self, memo: Any = None) -> List[Any]:
        return copy.deepcopy(list(self), memo if memo is not None else {})

    def __reduce__(self) -> Any:
        return (FrozenList, (list(self),))


def deep_freeze(value: Any) -> Any:
    """
    Deep-freeze one JSON tree, mirroring reference `deepFreeze` (index.ts:625)
    and `freezeRestoredObject` (index.ts:197).

    The reference freezes the borrowed graph IN PLACE and returns the same
    object. Python cannot retrofit immutability onto an existing `dict`/`list`,
    so the closest observable equivalent is returned instead: an already frozen
    value is returned unchanged, any other JSON container is copied into frozen
    containers (LEGAL_ADAPTATION: identity of the caller's container is not
    preserved, immutability of the session's durable copy is). The traversal is
    iterative, like the reference, so deep trees cannot exhaust the stack.
    """
    if type(value) is dict:
        root: Any = FrozenDict()
    elif type(value) is list:
        root = FrozenList()
    else:
        # Primitives are immutable in Python, and an already frozen container
        # needs no second pass, exactly like re-freezing in JavaScript.
        return value
    pending: List[Any] = [(value, root)]
    # `copies` maps each source container's id to the frozen target materialized
    # for it, so a graph that references one container twice (including a cycle)
    # terminates AND keeps that aliasing: the same source node always freezes to
    # the same target, mirroring the shared identity the reference's in-place
    # `Object.freeze` preserves (`deepFreeze`'s `seen` set, dsh-llm
    # call-config.ts:69-93).
    copies: Dict[int, Any] = {id(value): root}
    while pending:
        source, target = pending.pop()
        if type(source) is dict:
            for key in source:
                child = source[key]
                if type(child) is dict:
                    frozen_child = copies.get(id(child))
                    if frozen_child is None:
                        frozen_child = FrozenDict()
                        copies[id(child)] = frozen_child
                        pending.append((child, frozen_child))
                    dict.__setitem__(target, key, frozen_child)
                elif type(child) is list:
                    frozen_child = copies.get(id(child))
                    if frozen_child is None:
                        frozen_child = FrozenList()
                        copies[id(child)] = frozen_child
                        pending.append((child, frozen_child))
                    dict.__setitem__(target, key, frozen_child)
                else:
                    dict.__setitem__(target, key, child)
        else:
            for item in source:
                if type(item) is dict:
                    frozen_item = copies.get(id(item))
                    if frozen_item is None:
                        frozen_item = FrozenDict()
                        copies[id(item)] = frozen_item
                        pending.append((item, frozen_item))
                    list.append(target, frozen_item)
                elif type(item) is list:
                    frozen_item = copies.get(id(item))
                    if frozen_item is None:
                        frozen_item = FrozenList()
                        copies[id(item)] = frozen_item
                        pending.append((item, frozen_item))
                    list.append(target, frozen_item)
                else:
                    list.append(target, item)
    return root


#: The reference distinguishes `freezeRestoredObject` (index.ts:197, iterative)
#: from `deepFreeze` (index.ts:88 in dsh-llm, which also skips AbortSignal).
#: Python has no AbortSignal and both traversals are iterative here, so the two
#: names share one implementation.
freeze_restored_object = deep_freeze


def _is_negative_zero(val: float) -> bool:
    return val == 0.0 and math.copysign(1.0, val) < 0.0


def walk_json_value(value: Any, detach: bool = False, undefined_sentinel: Any = UNDEFINED) -> Any:
    """
    Validate lossless JSON iteratively without consuming the Python recursion stack.
    When detach=True, returns a fresh detached copy or undefined_sentinel on failure.
    When detach=False, returns True if valid, False otherwise.
    """
    ancestors: Set[int] = set()
    root_box = [undefined_sentinel]

    # Tasks stack: (kind, value, destination)
    tasks: List[Tuple[Any, ...]] = [("visit", value, ("root",))]

    while tasks:
        task = tasks.pop()
        kind = task[0]

        if kind == "leave":
            ancestors.remove(task[1])
            continue

        if kind == "visit":
            curr = task[1]
            dest = task[2]

            def _assign(val: Any) -> None:
                if not detach or dest is None:
                    return
                d_kind = dest[0]
                if d_kind == "root":
                    root_box[0] = val
                elif d_kind == "array":
                    dest[1][dest[2]] = val
                elif d_kind == "dict":
                    dest[1][dest[2]] = val

            # Scalars
            if curr is None or type(curr) is bool or type(curr) is str:
                _assign(curr)
                continue

            if type(curr) is int:
                _assign(curr)
                continue

            if type(curr) is float:
                if math.isnan(curr) or math.isinf(curr) or _is_negative_zero(curr):
                    return undefined_sentinel if detach else False
                _assign(curr)
                continue

            # Containers: strict list
            if type(curr) is list or type(curr) is FrozenList:
                ptr = id(curr)
                if ptr in ancestors:
                    return undefined_sentinel if detach else False
                ancestors.add(ptr)

                curr_len = len(curr)
                target = [None] * curr_len if detach else None
                _assign(target)

                tasks.append(("leave", ptr))
                for idx in reversed(range(curr_len)):
                    tasks.append(("visit", curr[idx], ("array", target, idx) if detach else None))
                continue

            # Containers: strict dict with str keys only
            if type(curr) is dict or type(curr) is FrozenDict:
                ptr = id(curr)
                if ptr in ancestors:
                    return undefined_sentinel if detach else False
                ancestors.add(ptr)

                target = {} if detach else None
                _assign(target)

                tasks.append(("leave", ptr))
                keys = list(curr.keys())
                for k in keys:
                    if type(k) is not str:
                        return undefined_sentinel if detach else False

                for k in reversed(keys):
                    tasks.append(("visit", curr[k], ("dict", target, k) if detach else None))
                continue

            # Any other type (custom class, set, tuple, function, object, etc.) is rejected
            return undefined_sentinel if detach else False

    return root_box[0] if detach else True


def is_json_value(value: Any) -> bool:
    """
    Test whether value survives JSON round-trip losslessly.
    1:1 with reference `isJsonValue(value)`.
    """
    return walk_json_value(value, detach=False) is True


def snapshot_json_value(value: Any, default: Any = None) -> Any:
    """
    Validate and detach lossless JSON in one pass.
    1:1 with reference `snapshotJsonValue(value)`.
    Returns default (None) when value is not losslessly JSON-serializable.
    """
    res = walk_json_value(value, detach=True, undefined_sentinel=UNDEFINED)
    if res is UNDEFINED:
        return default
    return res


# CamelCase aliases 1:1 with reference
isJsonValue = is_json_value
snapshotJsonValue = snapshot_json_value
