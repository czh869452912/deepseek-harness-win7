"""
Lossless-JSON validation and detached snapshots for durable session data.
Ported 1:1 from reference packages/core/session/src/json.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import math
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class _UndefinedType:
    def __repr__(self) -> str:
        return "undefined"

    def __bool__(self) -> bool:
        return False


UNDEFINED = _UndefinedType()


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
            if type(curr) is list:
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
            if type(curr) is dict:
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
