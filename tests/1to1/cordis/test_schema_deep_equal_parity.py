"""
1:1 parity tests for the unit `vendor/schemastery-cosmokit-deep-equal`.

reference/vendor/schemastery/src/index.ts:1 imports `deepEqual` from
`@deepseek-ai/cosmokit` and calls it at :408 (`simplify`) and :598 (`const`).
Cosmokit `deepEqual` (reference/vendor/cosmokit/src/types.ts:118-142) has two
branches this port must reproduce exactly:

- types.ts:129 - the array branch is
  `a.length === b.length && a.every((item, index) => deepEqual(item, b[index]))`,
  so it does NOT forward `strict` to its elements, while the object fallback at
  types.ts:141 is
  `Object.keys({ ...a, ...b }).every(key => deepEqual(a[key], b[key], strict))`,
  which does forward it.
- types.ts:141 - a key only one operand owns is read as `undefined`, which is
  distinct from `null` under `strict` and equal to it otherwise.

`simplify` maps the schema type onto that flag: `this.type === 'dict'`
(index.ts:408/417).  The oracle pinned by the migration contract is
`deepEqual({ k: [{ a: null }] }, { k: [{}] }, true) === true`.
"""

import pytest

from dsh.cordis.schema import Schema, ValidationError
from dsh.cordis.schema import deep_equal as schema_deep_equal
from dsh.cordis.utils import _UNDEFINED
from dsh.cordis.utils import deep_equal as cosmokit_deep_equal


def test_index_ts_1_schema_consumes_the_canonical_cosmokit_deep_equal():
    """index.ts:1: the schema module exposes cosmokit's own `deepEqual`.

    The port must not carry a private second implementation: the value the
    schema module publishes has to be the canonical `dsh.cordis.utils`
    function object itself.
    """
    assert schema_deep_equal is cosmokit_deep_equal


def test_types_ts_129_array_branch_does_not_forward_strict_acceptance_oracle():
    """types.ts:129: `deepEqual({k:[{a:null}]}, {k:[{}]}, true)` is true.

    The object fallback forwards `strict` (types.ts:141), the array branch does
    not (types.ts:129), so the element `{a:null}` is compared loosely against
    `{}` and passes.  The removed private copy forwarded the flag into the
    array branch and answered false.
    """
    assert cosmokit_deep_equal({"k": [{"a": None}]}, {"k": [{}]}, True) is True
    assert cosmokit_deep_equal([{"a": None}], [{}], True) is True
    # Loose and strict agree here: the array branch never sees the flag.
    assert cosmokit_deep_equal({"k": [{"a": None}]}, {"k": [{}]}, False) is True


def test_types_ts_129_array_branch_keeps_its_own_checks():
    """types.ts:129: the array branch still checks length and element-wise equality."""
    assert cosmokit_deep_equal([[None]], [[]], True) is False  # length differs
    assert cosmokit_deep_equal([None], [], True) is False
    assert cosmokit_deep_equal([True], [1], True) is False  # boolean !== number
    assert cosmokit_deep_equal([True], [1], False) is False
    assert cosmokit_deep_equal([{"a": None}], [{"b": None}], True) is True


def test_types_ts_141_object_fallback_forwards_strict():
    """types.ts:141: the object fallback passes `strict` to every key."""
    assert cosmokit_deep_equal({"a": None}, {}, True) is False
    assert cosmokit_deep_equal({"a": None}, {}, False) is True
    # The flag travels through nested objects, so an absent key inside a nested
    # object is `undefined` and no longer matches `null`.
    assert cosmokit_deep_equal({"a": {}}, {"a": {"b": None}}, True) is False
    assert cosmokit_deep_equal({"a": {}}, {"a": {"b": None}}, False) is True
    assert cosmokit_deep_equal({"a": 1}, {}, True) is False


def test_types_ts_141_absent_own_key_reads_as_undefined():
    """types.ts:141: `a[key]` for a key only `b` owns is `undefined`, not `null`.

    The port carries that value as its own `undefined` sentinel, so
    `deepEqual([undefined], [null])` is true loosely and false strictly.
    """
    assert cosmokit_deep_equal([_UNDEFINED], [None], False) is True
    assert cosmokit_deep_equal([_UNDEFINED], [None], True) is True  # array branch: loose
    assert cosmokit_deep_equal(_UNDEFINED, None, False) is True
    assert cosmokit_deep_equal(_UNDEFINED, None, True) is False


def test_index_ts_408_simplify_uses_strict_for_dict_and_loose_otherwise():
    """index.ts:408: `deepEqual(value, this.meta.default, this.type === 'dict')`.

    A dict-typed schema compares strictly, so an array of objects holding a
    `null` key still matches the default whose object omits that key, and the
    whole value simplifies away as already defaulted.
    """
    schema = Schema.dict(Schema.any()).default({"k": [{}]})
    assert schema.simplify({"k": [{"a": None}]}) is None

    # The same shape under a non-dict type compares loosely (also true here).
    assert Schema.any().default({"k": [{}]}).simplify({"k": [{"a": None}]}) is None

    # A dict-typed value that differs from the default keeps its result object.
    other = Schema.dict(Schema.any()).default({"k": [{}]})
    assert other.simplify({"k": [{"a": 1}]}) == {"k": [{"a": 1}]}


def test_index_ts_408_simplify_compares_even_without_a_default():
    """index.ts:408: the comparison runs even when `meta.default` is missing.

    `this.meta.default` is `undefined` then, so the port reads the absent meta
    key as its `undefined` sentinel: `simplify(undefined)` returns null, while
    a non-nullish value such as `{}` falls through to the type branches.
    """
    assert Schema.any().simplify(_UNDEFINED) is None
    assert Schema.any().simplify(None) is None
    assert Schema.any().simplify({}) == {}


def test_index_ts_417_simplify_object_result_compared_against_default():
    """index.ts:417: the built result object is compared against `meta.default`.

    The first comparison (index.ts:408) is false for the raw input, but the
    per-key `simplify` collapses the nested dict to `null`, and the rebuilt
    result then equals the default.
    """
    inner = Schema.dict(Schema.any()).default({"z": 1})
    outer = Schema.dict(inner).default({"a": None})
    assert outer.simplify({"a": {"z": 1}}) is None

    # Object-typed results drop nullish members, so the rebuilt `{}` equals the
    # factory default `{}` and the value simplifies away.
    inner_obj = Schema.object({"a": Schema.any()})
    outer_obj = Schema.object({"a": inner_obj}).default({})
    assert outer_obj.simplify({"a": {"a": None}}) is None


def test_index_ts_598_const_uses_loose_deep_equal():
    """index.ts:598: `deepEqual(data, value)` compares constants without strict.

    The array leniency therefore shows up for `const` too: a constant holding
    `[{a: null}]` accepts `[{}]` because the element comparison is loose.
    """
    schema = Schema.const([{"a": None}])
    assert schema([{}]) == [{"a": None}]
    # An element that really differs still fails, and the resolver reports the
    # reference's ValidationError (index.ts:599).
    with pytest.raises(ValidationError):
        schema([{"a": 1}])

    # The object fallback is loose here too: `{}` is missing the `a` key, so
    # `a[key]` reads as `undefined` and matches the constant's `null`.
    # `strict` is absent at :598, and the flag would have made this false.
    assert Schema.const({"a": None})({}) == {"a": None}
    with pytest.raises(ValidationError):
        Schema.const({"a": None})({"a": 1})
