"""Compare raw Loader config using schema metadata without evaluating config."""
from typing import Any, Set

from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED, deep_equal, is_nullable


def equal_except_volatile(previous: Any, next_value: Any, schema: Any) -> bool:
    if not isinstance(schema, Schema):return deep_equal(previous, next_value, True)
    def equal(left: Any, right: Any, node: Any, ancestors: Set[int]) -> bool:
        if node is not None and node.meta.get('volatile'):return True
        if node is None or node.type != 'object' or node.dict is None or id(node) in ancestors:
            return deep_equal(left, right, True)
        fallback=node.meta.get('default', _UNDEFINED)
        if is_nullable(left):left=fallback
        if is_nullable(right):right=fallback
        def record(value):return isinstance(value, dict) and '__jsExpr' not in value
        if not record(left) or not record(right):return deep_equal(left,right,True)
        ancestors.add(id(node))
        try:
            return all(equal(left.get(key,_UNDEFINED), right.get(key,_UNDEFINED), node.dict.get(key), ancestors)
                       for key in dict.fromkeys(list(left)+list(right)))
        finally:
            ancestors.remove(id(node))
    return equal(previous,next_value,schema,set())


equalExceptVolatile = equal_except_volatile
