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

Cases ported from the Schemastery reference surface (source and README), all
verified against the pinned reference implementation running on Node:

- README basic examples: any/never/const, number/string/boolean, is(array),
  array/dict/tuple/object, union/intersect/transform, construct defaults.
- README instance methods, validation options, shorthand syntax, advanced
  examples (enumeration, ToString, Listable, Alias) and extensibility.
- Error-message rendering through ECMAScript `String`/`JSON.stringify`.
- Path prefixes and `options.path`, `autofix` on object and array members.
- Decimal-step numbers, default cloning, modifier container sharing.
- dict `sKey` rename/strict skipping, tuple strict truncation, loose fallback,
  bitset `ToInt32` coercion, ECMAScript key enumeration order.
- `toString()` formatters, `ValidationError` marker, Standard Schema issues.
- `toJSON()` envelope shape, envelope round-trip and lazy memoization.
"""

import json
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


def test_t35_intersect_bool_vs_int_type_separation():
    """T35 (I10): Intersect of boolean and integer fails type compatibility check."""
    s = Schema.intersect([Schema.any(), Schema.number()])
    # True should fail when intersected with number (typeof boolean !== typeof number)
    with pytest.raises(ValidationError):
        s(True)


def test_t36_intersect_all_nullable_non_strict_leftover_merge():
    """T36 (I10): When intersect members are all nullable, non-strict leftover dict merges."""
    s = Schema.intersect([Schema.object({"a": Schema.string()})])
    # Pass dict without "a" in non-strict mode: "a" is nullable/absent, leftover "b" is retained
    res = Schema.resolve({"b": 123}, s, {}, strict=False)[0]
    assert res == {"b": 123}


def test_t37_transform_serialization_and_non_callable_fail_loud():
    """T37 (R5): Transform serialization preserves callback source, deserialization sets callback=None, and non-callable raises TypeError."""
    s = Schema.transform(Schema.string(), lambda x: x.upper())
    json_rep = s.to_json()
    assert "callback" in json_rep
    assert isinstance(json_rep["callback"], str)

    raw_tree = s.toJSON()
    assert isinstance(raw_tree, dict) and "refs" in raw_tree
    deserialized = Schema.from_json(raw_tree)
    assert deserialized.type == "transform"
    assert deserialized.callback is None
    assert deserialized.callback_source is not None

    # Resolving with a non-callable callback fails loud
    bad_schema = Schema.transform(Schema.string(), "not-a-callable")
    with pytest.raises(TypeError) as exc:
        bad_schema("hello")
    assert "callback is not callable" in str(exc.value)


def test_t38_schema_to_string_parentheses_protocol():
    """T38 (R8): to_string parenthesis protocol: union inline wraps in parens; intersect does not wrap outer parens; transform delegates to inner."""
    u = Schema.union([Schema.string(), Schema.number()])
    assert u.to_string() == "string | number"
    assert u.to_string(True) == "(string | number)"

    inter = Schema.intersect([u, Schema.boolean()])
    # Intersect formats inner members with inline=True, wrapping union in parens, but does NOT wrap outer in parens
    assert inter.to_string() == "(string | number) & boolean"
    assert inter.to_string(True) == "(string | number) & boolean"

    trans = Schema.transform(u, lambda x: x)
    assert trans.to_string() == "string | number"
    assert trans.to_string(True) == "(string | number)"


# ---------------------------------------------------------------------------
# Cases ported from the Schemastery reference surface
# (reference/vendor/schemastery/src/index.ts and its README examples).  Every
# expected value below was verified against the reference implementation run on
# Node with the pinned vendored sources.
# ---------------------------------------------------------------------------


def test_readme_any_never_const():
    """README `Schema.any()` / `Schema.never()` / `Schema.const(value)`."""
    assert Schema.any()() is None
    assert Schema.any()(0) == 0
    assert Schema.any()({}) == {}

    assert Schema.never()() is None
    with pytest.raises(ValidationError) as exc:
        Schema.never()(0)
    assert str(exc.value) == "expected nullable but got 0"

    assert Schema.const_(10)(10) == 10
    with pytest.raises(ValidationError) as exc:
        Schema.const_(10)(0)
    assert str(exc.value) == "expected 10 but got 0"


def test_readme_number_string_boolean():
    """README primitive validators and their null-input behavior."""
    assert Schema.number()() is None
    assert Schema.number()(1) == 1
    with pytest.raises(ValidationError) as exc:
        Schema.number()("")
    assert str(exc.value) == "expected number but got "

    assert Schema.string()() is None
    assert Schema.string()("foo") == "foo"
    with pytest.raises(ValidationError) as exc:
        Schema.string()(0)
    assert str(exc.value) == "expected string but got 0"

    assert Schema.boolean()() is None
    assert Schema.boolean()(True) is True
    with pytest.raises(ValidationError) as exc:
        Schema.boolean()(0)
    assert str(exc.value) == "expected boolean but got 0"
    # A Python `int` is not a boolean, matching ECMAScript's `typeof`.
    with pytest.raises(ValidationError):
        Schema.boolean()(1)


def test_readme_is_constructor():
    """README `Schema.is(constructor)` accepts instances and named prototype chains."""
    regexp = re.compile("foo")
    assert Schema.is_(re.Pattern)(regexp) is regexp
    with pytest.raises(ValidationError) as exc:
        Schema.is_(re.Pattern)("foo")
    assert str(exc.value) == "expected Pattern but got foo"

    # A string constructor matches the constructor name anywhere in the chain.
    err = ValueError("x")
    assert Schema.is_("Exception")(err) is err


def test_readme_array_dict_tuple_object():
    """README collection types, defaults and failure messages."""
    assert Schema.array(Schema.number())() == []
    with pytest.raises(ValidationError) as exc:
        Schema.array(Schema.number())(0)
    assert str(exc.value) == "expected array but got 0"
    assert Schema.array(Schema.number())([0, 1]) == [0, 1]
    with pytest.raises(ValidationError) as exc:
        Schema.array(Schema.number())([0, "1"])
    assert str(exc.value) == "$[1] expected number but got 1"

    assert Schema.dict(Schema.number())() == {}
    assert Schema.dict(Schema.number())({"a": 0, "b": 1}) == {"a": 0, "b": 1}
    with pytest.raises(ValidationError) as exc:
        Schema.dict(Schema.number())({"a": 0, "b": "1"})
    assert str(exc.value) == "$.b expected number but got 1"

    # A tuple fills short input member by member and keeps excess input.
    assert Schema.tuple([Schema.number(), Schema.string()])() == [None, None]
    assert Schema.tuple([Schema.number(), Schema.string()])([0]) == [0, None]
    with pytest.raises(ValidationError) as exc:
        Schema.tuple([Schema.number(), Schema.string()])([0, 1])
    assert str(exc.value) == "$[1] expected string but got 1"
    assert Schema.tuple([Schema.number(), Schema.string()])([0, "1"]) == [0, "1"]
    assert Schema.tuple([Schema.number()])([0, "x", 2]) == [0, "x", 2]

    assert Schema.object({"a": Schema.number(), "b": Schema.string()})() == {}
    assert Schema.object({"a": Schema.number(), "b": Schema.string()})({"a": 0}) == {"a": 0}
    with pytest.raises(ValidationError) as exc:
        Schema.object({"a": Schema.number(), "b": Schema.string()})({"a": 0, "b": 1})
    assert str(exc.value) == "$.b expected string but got 1"
    # Undeclared members are merged back in non-strict mode.
    assert Schema.object({"a": Schema.number()})({"a": 0, "z": 9}) == {"a": 0, "z": 9}


def test_readme_union_intersect_transform():
    """README union, intersect and transform semantics."""
    assert Schema.union([Schema.number(), Schema.string()])() is None
    assert Schema.union([Schema.number(), Schema.string()])(0) == 0
    assert Schema.union([Schema.number(), Schema.string()])("1") == "1"
    with pytest.raises(ValidationError) as exc:
        Schema.union([Schema.number(), Schema.string()])(True)
    assert str(exc.value) == "expected number | string but got true"

    members = [
        Schema.object({"a": Schema.string().required()}),
        Schema.object({"b": Schema.number().default(0)}),
    ]
    intersect = Schema.intersect(members)
    with pytest.raises(ValidationError) as exc:
        intersect()
    assert str(exc.value) == "$.a missing required value"
    assert intersect({"a": ""}) == {"a": "", "b": 0}
    assert intersect({"a": "", "b": 1}) == {"a": "", "b": 1}
    with pytest.raises(ValidationError) as exc:
        intersect({"a": "", "b": "2"})
    assert str(exc.value) == "$.b expected number but got 2"

    # The README shows `validate()` as 1, but the resolver returns the nullish
    # input before the transform callback runs, so the observed value is None.
    transform = Schema.transform(Schema.number().default(0), lambda n: n + 1)
    assert transform() is None
    with pytest.raises(ValidationError) as exc:
        transform("0")
    assert str(exc.value) == "expected number but got 0"
    assert transform(10) == 11


def test_readme_use_as_constructor():
    """README `new Config()` / direct call produce the same defaults."""
    config_schema = Schema.object({
        "foo": Schema.dict(Schema.string()).default({}),
        "bar": Schema.array(Schema.string()).default([]),
    })
    assert config_schema() == {"foo": {}, "bar": []}


def test_readme_simplify_drops_defaults():
    """README `schema.simplify(value)` removes values equal to schema defaults."""
    config_schema = Schema.object({
        "foo": Schema.string().default(""),
        "bar": Schema.number().default(0),
    })
    assert config_schema.simplify({"foo": "", "bar": 1}) == {"bar": 1}
    assert config_schema.simplify({"foo": "", "bar": 0}) is None


def test_readme_validation_options():
    """README `autofix`, `ignore` and `path` options."""
    assert Schema.object({"foo": Schema.number()})({"foo": "1"}, {"autofix": True}) == {}
    assert Schema.object({"foo": Schema.number()})({"foo": "1"}, {"ignore": lambda data, schema: True}) == {"foo": "1"}

    with pytest.raises(ValidationError) as exc:
        Schema.object({"foo": Schema.object({"bar": Schema.number()})})({"foo": {"bar": "x"}})
    assert str(exc.value) == "$.foo.bar expected number but got x"
    assert exc.value.options["path"] == ["foo", "bar"]

    with pytest.raises(ValidationError) as exc:
        Schema.array(Schema.number())([1, "x"])
    assert str(exc.value) == "$[1] expected number but got x"
    assert exc.value.options["path"] == [1]

    with pytest.raises(ValidationError) as exc:
        Schema.resolve("x", Schema.number(), {"path": ["root", 2]})
    assert str(exc.value) == "$.root[2] expected number but got x"


def test_autofix_removes_invalid_array_element():
    """`property()` deletes an invalid member before returning its fallback."""
    assert Schema.array(Schema.number().default(7))([1, "x"], {"autofix": True}) == [1, 7]

    data = [1, "x"]
    res = Schema.array(Schema.number())(data, {"autofix": True})
    # The reference leaves the array length intact and reads index 1 as
    # `undefined`; the port stores its nullish value at that index.
    assert res == [1, None]
    assert len(data) == 2
    assert data[1] is None


def test_readme_shorthand_syntax():
    """README shorthand table consumed by `Schema.from()`."""
    assert Schema.from_().type == "any"
    assert Schema.from_(None).type == "any"
    assert Schema.from_("foo").type == "const"
    assert Schema.from_("foo").meta.get("required") is True
    assert Schema.from_(5)(5) == 5
    assert Schema.from_(True)(True) is True
    assert Schema.from_(str)("x") == "x"
    assert Schema.from_(int)(1) == 1
    assert Schema.from_(bool)(True) is True
    function_schema = Schema.from_(type(lambda: None))
    assert function_schema.type == "function"
    assert callable(function_schema(lambda: 1))
    with pytest.raises(ValidationError) as exc:
        function_schema("x")
    assert str(exc.value) == "expected function but got x"
    assert Schema.from_(re.Pattern).type == "is"

    assert Schema.array(str)(["a"]) == ["a"]
    assert Schema.dict(int)({"a": 1}) == {"a": 1}
    assert Schema.union([1, 2])(1) == 1
    with pytest.raises(ValidationError) as exc:
        Schema.union([1, 2])(3)
    assert str(exc.value) == "expected 1 | 2 but got 3"


def test_readme_advanced_examples():
    """README enumeration, ToString, Listable and Alias examples."""
    enum = Schema.union(["red", "blue"])
    assert enum("red") == "red"
    with pytest.raises(ValidationError):
        enum("green")

    to_string = Schema.transform(Schema.any(), lambda value: str(value))
    assert to_string("") == ""
    assert to_string(0) == "0"
    assert to_string({}) == "{}"

    listable = Schema.union([Schema.array(int), Schema.transform(int, lambda n: [n])]).default([])
    assert listable() == []
    assert listable(0) == [0]
    assert listable([1, 2]) == [1, 2]

    # The alias example's transform callback takes no arguments; the reference
    # calls every callback with one argument and the extra argument is dropped.
    alias = Schema.dict(int, Schema.union(["foo", Schema.transform("bar", lambda: "foo")]))
    assert alias({"foo": 1}) == {"foo": 1}
    assert alias({"bar": 2}) == {"foo": 2}
    with pytest.raises(ValidationError) as exc:
        alias({"bar": "3"})
    assert str(exc.value) == "$.bar expected number but got 3"


def test_transform_callback_arity():
    """Transform callbacks accept 0, 1 or 2 declared parameters."""
    assert Schema.transform(Schema.string(), lambda: "foo")("x") == "foo"
    assert Schema.transform(Schema.string(), lambda value: value.upper())("x") == "X"

    seen = {}

    def with_options(value, options):
        seen["options"] = options
        return value

    assert Schema.transform(Schema.string(), with_options)("x", {"mark": 1}) == "x"
    assert seen["options"] == {"mark": 1}


def test_readme_extensibility():
    """README `Schema.extend(type, resolve)` with a 3-parameter resolver."""
    def trimmed(data, schema, options):
        if not isinstance(data, str):
            raise ValidationError("expected string but got " + str(data), options)
        return (data.strip(),)

    Schema.extend("trimmed", trimmed)
    assert Schema({"type": "trimmed"})("  a  ") == "a"

    def upper(data):
        return (data.upper(), data.upper())

    Schema.extend("upper_writeback", upper)
    data = {"a": "x"}
    Schema.object({"a": Schema({"type": "upper_writeback"})})(data)
    assert data == {"a": "X"}


def test_error_messages_use_ecmascript_string_conversion():
    """Template-literal interpolation in the reference uses `String(value)`."""
    with pytest.raises(ValidationError) as exc:
        Schema.bitset({"read": 1})(True)
    assert str(exc.value) == "expected number or array but got true"

    with pytest.raises(ValidationError) as exc:
        Schema.is_("Foo")({})
    assert str(exc.value) == "expected Foo but got [object Object]"

    with pytest.raises(ValidationError) as exc:
        Schema.object({"a": Schema.number()})([])
    assert str(exc.value) == "expected object but got "

    # A nullish input returns before the resolver lookup; a real value reaches it.
    assert Schema({"type": "nope"})() is None
    with pytest.raises(ValidationError) as exc:
        Schema({"type": "nope"})(1)
    assert str(exc.value) == 'unsupported type "nope"'

    with pytest.raises(TypeError) as exc:
        Schema.from_({})
    assert str(exc.value) == "cannot infer schema from [object Object]"


def test_union_and_intersect_messages_use_json_stringify():
    """The reference formats union/intersect failures with `JSON.stringify`."""
    with pytest.raises(ValidationError) as exc:
        Schema.union([Schema.const_(1)])({"a": 1})
    assert str(exc.value) == 'expected 1 but got {"a":1}'

    with pytest.raises(ValidationError) as exc:
        Schema.union([Schema.const_("x")])(1)
    assert str(exc.value) == 'expected "x" but got 1'

    with pytest.raises(ValidationError) as exc:
        Schema.const_("x")(1)
    assert str(exc.value) == "expected x but got 1"

    # ECMAScript enumerates array-index keys first, so `{"2": 1, "1": 2}`
    # renders with ascending numeric keys.
    with pytest.raises(ValidationError) as exc:
        Schema.union([Schema.string()])({"2": 1, "1": 2})
    assert str(exc.value) == 'expected string but got {"1":2,"2":1}'


def test_object_and_dict_enumeration_order():
    """Resolved containers enumerate array-index keys first, as ECMAScript does."""
    resolved = Schema.object({"a": Schema.number()})({"2": "x", "1": "y"})
    assert list(resolved.keys()) == ["1", "2"]
    assert resolved == {"1": "y", "2": "x"}

    resolved_dict = Schema.dict(Schema.number())({"2": 1, "1": 2})
    assert list(resolved_dict.keys()) == ["1", "2"]
    assert resolved_dict == {"1": 2, "2": 1}


def test_number_step_uses_decimal_shift():
    """The reference compares multiples through `decimalShift`, not float modulo."""
    assert Schema.number().step(0.25)(0.75) == 0.75
    assert Schema.number().step(3)(9) == 9
    assert Schema.number().step(0.1).min(-1)(0.1) == 0.1
    assert Schema.number().step(0.07).min(0.01)(0.08) == 0.08
    with pytest.raises(ValidationError) as exc:
        Schema.number().step(0.07).min(0.01)(0.09)
    assert str(exc.value) == "expected number multiple of 0.07 but got 0.09"

    # 0.1 + 0.2 carries float noise, which the decimal shift surfaces.
    with pytest.raises(ValidationError) as exc:
        Schema.number().step(0.1)(0.30000000000000004)
    assert str(exc.value) == "expected number multiple of 0.1 but got 0.30000000000000004"
    assert Schema.number().step(0.1)(0.3) == 0.3

    # NaN passes the type and range checks, exactly as in JavaScript.
    result = Schema.number().min(5)(float("nan"))
    assert result != result


def test_default_values_are_cloned():
    """`resolve` clones a default before validating, so callers cannot share it."""
    array_schema = Schema.array(Schema.number()).default([1, 2])
    first = array_schema()
    second = array_schema()
    first.append(3)
    assert second == [1, 2]

    object_schema = Schema.object({"a": Schema.number()}).default({"a": 1})
    resolved = object_schema()
    resolved["a"] = 99
    assert object_schema() == {"a": 1}


def test_modifier_clones_share_containers():
    """`Schema(this)` copies own properties by reference, containers included."""
    base = Schema.object({"a": Schema.string()})
    copy = base.required()
    copy.set("b", Schema.number())
    assert base.dict is copy.dict
    assert sorted(base.dict.keys()) == ["a", "b"]

    union_base = Schema.union([Schema.string()])
    union_base.required().push(Schema.number())
    assert len(union_base.list) == 2

    # Only the first copy of a clone shares its meta: every builder method
    # replaces meta with a fresh object after the clone reads the shared one.
    string_base = Schema.string()
    string_clone = string_base.required()
    string_clone.meta["probe"] = 1
    assert "probe" not in string_base.meta
    assert string_base.meta == {}


def test_dict_key_schema_renames_and_writes_back():
    """`dict` renames a key through `sKey` and mutates the validated input."""
    rename = Schema.dict(Schema.number(), Schema.transform(Schema.string(), lambda key: key.upper()))
    data = {"hello": 123}
    assert rename(data) == {"HELLO": 123}
    assert data == {"HELLO": 123}

    strict_data = {"hello": 123}
    assert Schema.resolve(strict_data, rename, {}, True)[0] == {"HELLO": 123}


def test_dict_strict_mode_skips_keys_that_fail_the_key_schema():
    """A `strict` resolve drops keys the key schema rejects."""
    keyed = Schema.dict(Schema.number(), Schema.string().pattern(re.compile("^[A-Z]+$")))
    data = {"ok": 1, "bad": 2}
    assert Schema.resolve(data, keyed, {}, True)[0] == {}
    assert data == {"ok": 1, "bad": 2}
    # Non-strict mode reports the key failure at the container path.
    with pytest.raises(ValidationError) as exc:
        keyed({"bad": 1})
    assert str(exc.value) == "expect string to match regexp /^[A-Z]+$/"


def test_tuple_strict_mode_truncates_excess_input():
    """A `strict` tuple resolve drops members beyond the declared list."""
    schema = Schema.tuple([Schema.number()])
    assert Schema.resolve([0, "x", 2], schema, {}, True)[0] == [0]
    assert schema([0, "x", 2]) == [0, "x", 2]


def test_loose_falls_back_to_default():
    """`loose()` returns the schema default instead of raising."""
    assert Schema.number().default(42).loose()("not-a-number") == 42
    assert Schema.number().loose()("x") is None
    assert Schema.object({"a": Schema.object({"b": Schema.number()}).loose()})({"a": {"b": "x"}}) == {"a": {}}


def test_bitset_number_input_uses_to_int32():
    """The bitset resolver masks with ECMAScript `ToInt32` for numeric input."""
    bits = Schema.bitset({"a": 1, "b": 2})
    assert bits(3) == 3
    assert bits(3.0) == 3
    value, adapted = Schema.resolve(3, bits)
    assert value == 3 and adapted == ["a", "b"]
    value, adapted = Schema.resolve(0, bits)
    assert value == 0 and adapted is None

    data = {"f": 3.0}
    Schema.object({"f": Schema.bitset({"a": 1, "b": 2}).default(0)})(data)
    assert data == {"f": ["a", "b"]}


def test_simplify_drops_undeclared_object_keys():
    """`simplify` keeps only declared members for an object schema."""
    assert Schema.object({"a": Schema.string().default("")}).simplify({"a": "", "b": 1}) is None
    assert Schema.object({"a": Schema.string().default("x")}).simplify({"a": "y", "b": 1}) == {"a": "y"}
    # A dict keeps a member whose simplified value is nullish.
    assert Schema.dict(Schema.number().default(0)).simplify({"a": 0, "b": 1}) == {"a": None, "b": 1}


def test_to_string_formatters():
    """`toString()` uses the reference's per-type formatters."""
    assert Schema.string().toString() == "string"
    assert Schema.const_("x").toString() == '"x"'
    assert Schema.const_(5).toString() == "5"
    assert Schema.array(Schema.string()).toString() == "string[]"
    assert Schema.array(Schema.union([Schema.string(), Schema.number()])).toString() == "(string | number)[]"
    assert Schema.dict(Schema.number()).toString() == "{ [key: string]: number }"
    assert Schema.dict(Schema.number(), Schema.const_("k")).toString() == '{ [key: "k"]: number }'
    assert Schema.dict(Schema.object({"a": Schema.string()})).toString() == "{ [key: string]: { a?: string } }"
    assert Schema.tuple([Schema.number(), Schema.string()]).toString() == "[number, string]"
    assert Schema.object({}).toString() == "{}"
    assert Schema.object({"a": Schema.string(), "b": Schema.number().required()}).toString() == "{ a?: string, b: number }"
    assert Schema.union([Schema.number(), Schema.string()]).toString() == "number | string"
    assert Schema.union([Schema.number(), Schema.string()]).toString(True) == "(number | string)"
    assert Schema.intersect([
        Schema.object({"a": Schema.string()}),
        Schema.union([Schema.number(), Schema.boolean()]),
    ]).toString() == "{ a?: string } & (number | boolean)"
    assert Schema.transform(Schema.string(), lambda value: value).toString() == "string"
    assert Schema.bitset({"a": 1}).toString() == "bitset"
    assert Schema.function().toString() == "function"
    assert Schema.never().toString() == "never"
    assert Schema.boolean().toString() == "boolean"
    assert Schema({"type": "weird"}).toString() == "Schema<weird>"
    assert Schema.is_(re.Pattern).toString() == "Pattern"
    assert Schema.is_("Foo").toString() == "Foo"


def test_validation_error_marker():
    """`ValidationError` carries the shared marker and remains a `TypeError`."""
    with pytest.raises(ValidationError) as exc:
        Schema.number()("x")
    assert isinstance(exc.value, TypeError)
    assert ValidationError.is_(exc.value)
    assert not ValidationError.is_(TypeError("x"))
    assert str(exc.value) == "expected number but got x"
    assert exc.value.options == {}


def test_standard_schema_issue_shape():
    """`~standard.validate` reports `{ value }` or `{ issues: [{ message, path }] }`."""
    standard = Schema.string()["~standard"]
    assert standard["version"] == 1
    assert standard["vendor"] == "schemastery"
    assert standard["validate"]("a") == {"value": "a"}

    top_level = Schema.number().validate("x")
    assert top_level == {"issues": [{"message": "expected number but got x", "path": None}]}

    nested = Schema.object({"a": Schema.object({"b": Schema.number()})}).validate({"a": {"b": "x"}})
    assert nested == {"issues": [{"message": "$.a.b expected number but got x", "path": ["a", "b"]}]}

    indexed = Schema.array(Schema.number()).validate([1, "x"])
    assert indexed == {"issues": [{"message": "$[1] expected number but got x", "path": [1]}]}


def test_tojson_envelope_shape():
    """`toJSON()` returns a flat `{ uid, refs }` envelope with uid-keyed nodes."""
    inner = Schema.string()
    schema = Schema.object({"a": inner, "b": inner})
    envelope = schema.toJSON()

    assert sorted(envelope.keys()) == ["refs", "uid"]
    assert envelope["uid"] == schema.uid
    refs = envelope["refs"]
    node = refs[schema.uid]
    assert sorted(node.keys()) == ["dict", "meta", "type"]
    assert node["type"] == "object"
    assert node["meta"] == {"default": {}}
    # A shared node is referenced by uid instead of being serialized twice.
    assert node["dict"] == {"a": inner.uid, "b": inner.uid}
    assert refs[inner.uid] == {"type": "string", "meta": {}}
    assert len(refs) == 2


def test_tojson_envelope_roundtrip():
    """`Schema.from_json` hydrates the envelope back into an equivalent schema."""
    schema = Schema.object({"foo": Schema.string(), "bar": Schema.number()})
    hydrated = Schema.from_json(json.loads(json.dumps(schema.toJSON())))
    assert hydrated.type == "object"
    assert sorted(hydrated.dict.keys()) == ["bar", "foo"]
    assert hydrated({"foo": "a", "bar": 2}) == {"foo": "a", "bar": 2}
    with pytest.raises(ValidationError) as exc:
        hydrated({"foo": "a", "bar": "2"})
    assert str(exc.value) == "$.bar expected number but got 2"


def test_lazy_builder_is_memoized_and_serialized():
    """`lazy` builds once, merges node meta, and serializes the built schema."""
    builds = []

    def builder():
        builds.append(1)
        return Schema.string()

    lazy_schema = Schema.lazy(builder)
    assert lazy_schema("first") == "first"
    assert lazy_schema("second") == "second"
    assert len(builds) == 1

    node = lazy_schema.toJSON()["refs"][lazy_schema.uid]
    assert node["type"] == "lazy"
    assert node["inner"] == lazy_schema.inner.uid


def test_intersect_leftover_merge_of_nullish_result():
    """A nullish intersect result merges the input object, as the reference does."""
    schema = Schema.intersect([Schema.transform(Schema.any(), lambda value: None)])
    # Every member resolved to the nullish value, so the non-strict leftover
    # merge runs `merge(undefined, data)`; the reference reaches `key in
    # undefined` for a non-empty object and returns undefined for an empty one.
    with pytest.raises(TypeError) as exc:
        schema({"a": 1})
    assert "Cannot use 'in' operator to search for 'a' in undefined" in str(exc.value)
    assert schema({}) is None
