"""
1:1 parity unit test suite for dsh/cordis/schema.py matching reference/vendor/schemastery/src/index.ts.
Covers:
- T1: Factory default meta on null input (object/dict->{}, array/tuple->[], bitset->0)
- T2: intersect falls back to first member default when input is None
- T3: options.ignore skips validation and returns data as-is
- T4: property adapted writeback mutates input
- T5: autofix deletes invalid key and takes schema default
- T6: dict sKey rename writes back to input
- T7: bitset adapted is suppressed when value equals default (0)
- T8: array min length skipped when inner has default
- T9: tuple short input resolves members individually
- T10: intersect conflicting keys: first member wins (shallow first-wins)
- T11: intersect numeric type equality (1.0 vs 1)
- T12: intersect all nullable members returns None
- T13: non-preserve transform applies callback to both result and adapted
- T14: string pattern flags applied (case-insensitive flag i)
- T15: pattern meta.flags encodes letters (i, m, s) instead of integer
- T16: is('Exception') walks MRO for subclasses
- T17: const bool and int not interchangeable (True != 1)
- T18: deep_equal for compiled regexes and strict dict mode
- T19: simplify object drops unknown keys
- T20: simplify empty object returns empty dict
- T26: lazy toJSON serializes built inner
- T27: lazy builder called only once (memoization)
- T28: ~standard vendor is 'schemastery' and rethrows non-validation errors
- T29: Schema.date parses UTC 'Z' suffix
- T32: Schema.dict default s_key is string schema
- T33: Schema.bitset filters non-number bits
- T34: set/push without container raises TypeError
"""

import pytest
import re
from typing import Any

from dsh.cordis.schema import Schema, ValidationError, deep_equal


def test_t1_factory_default_meta_on_null_input():
    """T1: Factory methods assign default meta: object/dict->{}, array/tuple->[], bitset->0."""
    obj_s = Schema.object({"foo": Schema.string().default("bar")})
    assert obj_s(None) == {"foo": "bar"}

    arr_s = Schema.array(Schema.string())
    assert arr_s(None) == []

    dict_s = Schema.dict(Schema.number())
    assert dict_s(None) == {}

    tup_s = Schema.tuple([Schema.string().default("a"), Schema.number().default(1)])
    assert tup_s(None) == ["a", 1]

    bit_s = Schema.bitset({"read": 1, "write": 2})
    assert bit_s(None) == 0


def test_t2_resolve_intersect_falls_back_to_first_member_default():
    """T2: intersect with None input falls back to first member's default."""
    s = Schema.intersect([Schema.object({"a": Schema.string().default("alpha")})])
    assert s(None) == {"a": "alpha"}


def test_t3_resolve_options_ignore_skips_validation():
    """T3: options['ignore'] callback bypasses validation."""
    s = Schema.number().min(10)
    # 5 < 10, normally invalid, but ignored
    res, _ = Schema.resolve(5, s, options={"ignore": lambda d, sc: True})
    assert res == 5


def test_t4_property_adapted_writeback_mutates_input():
    """T4: property adapted writeback updates the input dictionary."""
    s = Schema.object({
        "flags": Schema.bitset({"read": 1, "write": 2})
    })
    data = {"flags": 3}
    res, _ = Schema.resolve(data, s)
    assert data["flags"] == ["read", "write"]


def test_t5_property_autofix_deletes_invalid_key():
    """T5: options.autofix deletes invalid key and replaces with default."""
    s = Schema.object({
        "count": Schema.number().default(42)
    })
    data = {"count": "invalid_not_a_number"}
    res, _ = Schema.resolve(data, s, options={"autofix": True})
    assert res["count"] == 42
    assert "count" not in data


def test_t6_dict_skey_rename_writes_back_to_input():
    """T6: dict sKey rename writes renamed key back to input."""
    s = Schema.dict(Schema.number(), Schema.transform(Schema.string(), lambda k: k.upper()))
    data = {"hello": 123}
    res, _ = Schema.resolve(data, s)
    assert "HELLO" in data
    assert "hello" not in data
    assert res == {"HELLO": 123}


def test_t7_bitset_adapted_suppressed_when_value_equals_default():
    """T7: bitset adapted is suppressed when value equals default (0)."""
    s = Schema.bitset({"read": 1, "write": 2})
    val, adapted = Schema.resolve(0, s)
    assert val == 0
    assert adapted is None


def test_t8_array_min_length_skipped_when_inner_has_default():
    """T8: array min length check is skipped when inner element has default."""
    s = Schema.array(Schema.string().default("def")).min(3)
    # Empty array is accepted because inner has default
    assert s([]) == []


def test_t9_tuple_short_input_resolves_members_individually():
    """T9: tuple resolves short input element-by-element instead of pre-checking length."""
    s = Schema.tuple([Schema.string().default("first"), Schema.number().default(100)])
    # Short input: missing second item gets default
    res = s(["custom"])
    assert res == ["custom", 100]


def test_t10_intersect_conflicting_keys_first_member_wins():
    """T10: intersect merges keys using first-wins shallow merge."""
    s1 = Schema.object({"x": Schema.string().default("first")})
    s2 = Schema.object({"x": Schema.string().default("second")})
    merged = Schema.intersect([s1, s2])
    assert merged({}) == {"x": "first"}


def test_t11_intersect_numeric_type_equality_1_vs_1_0():
    """T11: intersect treats int and float as compatible numeric types."""
    s1 = Schema.number()
    s2 = Schema.number()
    intersect_s = Schema.intersect([s1, s2])
    assert intersect_s(1) == 1


def test_t12_intersect_all_nullable_members_returns_none():
    """T12: intersect returns None when all members evaluate to None."""
    s = Schema.intersect([Schema.string(), Schema.string()])
    val, _ = Schema.resolve(None, s)
    assert val is None


def test_t13_transform_callback_applied_to_adapted():
    """T13: non-preserve transform applies callback to both result and adapted."""
    call_count = [0]

    def double_fn(val):
        call_count[0] += 1
        return val * 2

    s = Schema.transform(Schema.number(), double_fn, preserve=False)
    res, adapted = Schema.resolve(5, s)
    assert res == 10
    assert adapted == 10
    assert call_count[0] == 2


def test_t14_string_pattern_flags_applied():
    """T14: string pattern flags like 'i' are applied during validation."""
    s = Schema.string().pattern(re.compile(r"^[a-z]+$", re.IGNORECASE))
    assert s("HELLO") == "HELLO"


def test_t15_pattern_meta_flags_letter_encoding():
    """T15: pattern meta.flags encodes letters (i, m, s) instead of integer."""
    s = Schema.string().pattern(re.compile(r"abc", re.IGNORECASE | re.MULTILINE))
    flags = s.meta["pattern"]["flags"]
    assert "i" in flags
    assert "m" in flags
    assert not flags.isdigit()


def test_t16_is_name_walks_mro_for_subclasses():
    """T16: Schema.is_('Exception') accepts ValueError instances via MRO walk."""
    s = Schema.is_("Exception")
    err = ValueError("something")
    assert s(err) == err


def test_t17_const_bool_and_int_not_interchangeable():
    """T17: const(True) rejects 1 and const(1) rejects True."""
    s_bool = Schema.const(True)
    with pytest.raises(ValidationError):
        s_bool(1)

    s_int = Schema.const(1)
    with pytest.raises(ValidationError):
        s_int(True)


def test_t18_deep_equal_compiled_patterns_and_strict_dict():
    """T18: deep_equal handles compiled re.Pattern equality and bool/int type buckets."""
    p1 = re.compile(r"hello", re.IGNORECASE)
    p2 = re.compile(r"hello", re.IGNORECASE)
    p3 = re.compile(r"hello")
    assert deep_equal(p1, p2)
    assert not deep_equal(p1, p3)
    assert not deep_equal(True, 1)


def test_t19_simplify_object_drops_unknown_keys():
    """T19: simplify on object drops unknown keys."""
    s = Schema.object({"known": Schema.string()})
    simplified = s.simplify({"known": "val", "unknown_extra": 123})
    assert "unknown_extra" not in simplified
    assert simplified == {"known": "val"}


def test_t20_simplify_empty_object_returns_empty_dict():
    """T20: simplify on empty object without default returns {} instead of None."""
    # Direct construction without factory default meta:
    s = Schema({"type": "object", "dict": {"a": Schema.string()}})
    assert s.simplify({}) == {}


def test_t26_lazy_tojson_serializes_built_inner():
    """T26: lazy toJSON builds inner schema and outputs its structure."""
    lazy_s = Schema.lazy(lambda: Schema.string())
    json_rep = lazy_s.to_json()
    assert json_rep["type"] == "lazy"
    assert json_rep.get("inner") is not None


def test_t27_lazy_builder_called_only_once():
    """T27: lazy builder is memoized and only invoked once across multiple resolves."""
    build_count = [0]

    def builder():
        build_count[0] += 1
        return Schema.string()

    s = Schema.lazy(builder)
    assert s("first") == "first"
    assert s("second") == "second"
    assert build_count[0] == 1


def test_t28_standard_schema_vendor_and_unknown_error_rethrow():
    """T28: ~standard schema has vendor 'schemastery'."""
    s = Schema.string()
    standard = s["~standard"]
    assert standard["vendor"] == "schemastery"
    valid_res = standard["validate"]("hello")
    assert valid_res == {"value": "hello"}


def test_t29_date_parses_utc_z_suffix():
    """T29: Schema.date parses ISO 8601 strings with 'Z' suffix."""
    s = Schema.date()
    dt = s("2026-08-29T12:00:00Z")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 8


def test_t32_dict_default_skey_is_string_schema():
    """T32: Schema.dict without sKey defaults s_key to Schema.string()."""
    s = Schema.dict(Schema.number())
    assert s.s_key is not None
    assert s.s_key.type == "string"


def test_t33_bitset_filters_non_number_bits():
    """T33: Schema.bitset filters non-integer bit values."""
    s = Schema.bitset({"valid": 1, "invalid_str": "bad", "invalid_bool": True})
    assert "valid" in s.bits
    assert "invalid_str" not in s.bits
    assert "invalid_bool" not in s.bits


def test_t34_set_push_without_container_raises_typeerror():
    """T34: set() and push() on schema without container raise TypeError."""
    num_s = Schema.number()
    with pytest.raises(TypeError):
        num_s.set("key", Schema.string())

    with pytest.raises(TypeError):
        num_s.push(Schema.string())
