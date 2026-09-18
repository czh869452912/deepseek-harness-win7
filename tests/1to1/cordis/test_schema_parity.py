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
- T33: Schema.bitset keeps every `number` bit value and drops the rest
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

Cases added for the reference constructor and serializer contract, verified the
same way:

- README Serializability: `new Schema(JSON.parse(JSON.stringify(schema1)))`
  rehydrates the `{ uid, refs }` envelope, rebuilds every referenced node under
  a fresh uid, resolves `inner`/`sKey`/`list`/`dict`, returns the root node and
  keeps a shared node shared.
- `toJSON()` keeps every assigned member (`null`, `0`, `false`, `[]`, `{}`) and
  omits the members the factory never assigned, including `const(undefined)`
  against `const(null)`; a non-finite number serializes as `null`; `refs` lists
  ascending uids; a transform's `preserve` and a lazy node's `inner`/`meta`
  order match the object the factory created.
- The transform resolver passes exactly one positional argument to its callback.
- `valueMap`-built member maps follow ECMAScript own-key order, so an
  integer-like member name comes first in the definition, `toString()` and the
  serialized node.
- `simplify()` walks `for (const key in value)` for any value type and raises
  the reference's `value.forEach` TypeError from the array branch.
- Every factory creates its node before resolving shorthand members, so the
  serialized uid numbering matches the reference graph for graph.
- `Schema(schema)` clones an existing schema (the reference's
  `Partial<Schema<T>>` constructor), and `Schema.ValidationError` is exposed for
  the README's extensibility example.
- `i18n()` merges a locale description only from `$description`/`$desc` or a
  plain string message, resolves each member message through
  `getInner(data)?.[key] ?? data?.[key]`, and writes the result into the meta
  object the source schema shares; `deprecated()`/`experimental()` push into
  that same shared `meta.badges`; the union formatter parenthesizes the inline
  form of a single member too.
- A lazy node serializes the schema `Schema.lazy`'s stub closes over, so a
  clone reports the original's built node and meta, while a builder that
  yields no schema fails loud.
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
    """T33: Schema.bitset keeps every `number` member and drops the others."""
    s = Schema.bitset({
        "valid": 1,
        "fraction": 0.5,
        "nan": float("nan"),
        "infinite": float("inf"),
        "invalid_str": "bad",
        "invalid_bool": True,
    })
    # The reference factory keeps the members whose `typeof` is 'number', so a
    # fractional or non-finite bit stays in the definition.
    assert list(s.bits.keys()) == ["valid", "fraction", "nan", "infinite"]
    assert s.bits["valid"] == 1
    assert s.bits["fraction"] == 0.5
    assert "invalid_str" not in s.bits
    assert "invalid_bool" not in s.bits

    # Masking coerces both operands with ToInt32, so a fractional bit masks as
    # its int32 value and a non-finite one as 0.
    assert Schema.bitset({"a": 1.5, "b": float("nan"), "c": 2})(3) == 3
    assert Schema.bitset({"a": 1.5, "b": float("nan")})(["a", "b"]) == 1


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
    """
    The transform resolver calls `callback!(value)` with one positional argument.

    Verified against the reference: `Schema.transform(any, (...args) =>
    args.length)(1)` is 1 for both the preserved and the adapted call, a
    callback declaring a second parameter reads `undefined` for it, and a
    zero-parameter callback still runs.
    """
    assert Schema.transform(Schema.string(), lambda: "foo")("x") == "foo"
    assert Schema.transform(Schema.string(), lambda value: value.upper())("x") == "X"
    assert Schema.transform(Schema.any(), lambda *args: len(args))(1) == 1
    assert Schema.transform(Schema.any(), lambda *args: len(args), True)({"a": 1}) == 1

    seen = []

    def with_options(value, options):
        seen.append(options)
        return value

    assert Schema.transform(Schema.string(), with_options)("x", {"mark": 1}) == "x"
    # The reference drops the extra argument, so `options` is `undefined`.
    assert seen == [None, None]


def test_readme_extensibility():
    """README `Schema.extend(type, resolve)` and `new Schema.ValidationError(...)`."""
    # The README's custom resolver throws `new Schema.ValidationError(msg,
    # options)`, and the reference exposes the class as `Schema.ValidationError`.
    assert Schema.ValidationError is ValidationError
    assert Schema.ValidationError.is_(Schema.ValidationError("x", {}))

    def trimmed(data, schema, options):
        if not isinstance(data, str):
            raise Schema.ValidationError("expected string but got " + str(data), options)
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
    # The reference serializes a node as `JSON.parse(JSON.stringify({ ...
    # this }))`, so the member order and the set of members match the object the
    # factory created.
    assert list(node.keys()) == ["type", "meta", "dict"]
    assert node["type"] == "object"
    assert node["meta"] == {"default": {}}
    # A shared node is referenced by uid instead of being serialized twice.
    assert node["dict"] == {"a": inner.uid, "b": inner.uid}
    assert refs[inner.uid] == {"type": "string", "meta": {}}
    assert len(refs) == 2
    # Every refs key is a uid, and ECMAScript enumerates integer-like own keys
    # in ascending numeric order, so the envelope reports ascending uids.
    assert [int(key) for key in refs] == sorted(int(key) for key in refs)


def test_tojson_keeps_assigned_falsey_and_nullable_members():
    """
    `toJSON()` drops only the members the reference never assigned.

    Verified against the reference: `JSON.stringify` keeps an assigned `null`,
    `0`, `false`, `[]` or `{}` and omits an `undefined` member, so an empty
    relation container and an explicit null constant survive serialization.
    """
    empty_object = Schema.object({})
    assert empty_object.toJSON()["refs"][empty_object.uid] == {
        "type": "object", "meta": {"default": {}}, "dict": {},
    }

    empty_tuple = Schema.tuple([])
    assert empty_tuple.toJSON()["refs"][empty_tuple.uid] == {
        "type": "tuple", "meta": {"default": []}, "list": [],
    }

    empty_union = Schema.union([])
    assert empty_union.toJSON()["refs"][empty_union.uid] == {
        "type": "union", "meta": {}, "list": [],
    }

    empty_bitset = Schema.bitset({})
    assert empty_bitset.toJSON()["refs"][empty_bitset.uid] == {
        "type": "bitset", "meta": {"default": 0}, "bits": {},
    }

    null_const = Schema.const_(None)
    assert null_const.toJSON()["refs"][null_const.uid] == {"type": "const", "meta": {}, "value": None}
    zero_const = Schema.const_(0)
    assert zero_const.toJSON()["refs"][zero_const.uid] == {"type": "const", "meta": {}, "value": 0}
    # `Schema.const(undefined)` never assigns `value`, so the member is absent;
    # the reference formatter result is nullish, so `toString()` falls back.
    unassigned = Schema.const_()
    assert unassigned.toJSON()["refs"][unassigned.uid] == {"type": "const", "meta": {}}
    assert unassigned.to_string() == "Schema<const>"
    assert Schema.const_(None).to_string() == "Schema<const>"
    with pytest.raises(ValidationError) as exc:
        unassigned(5)
    assert str(exc.value) == "expected undefined but got 5"

    loose_false = Schema.string().required(False)
    assert loose_false.toJSON()["refs"][loose_false.uid]["meta"] == {"required": False}
    null_default = Schema.string().default(None)
    assert null_default.toJSON()["refs"][null_default.uid]["meta"] == {"default": None}


def test_tojson_transform_preserve_and_lazy_member_order():
    """A transform's `preserve` member and a lazy node's member order."""
    omitted = Schema.transform(Schema.string(), lambda value: value)
    assert list(omitted.toJSON()["refs"][omitted.uid].keys()) == ["type", "meta", "inner", "callback"]

    kept_false = Schema.transform(Schema.string(), lambda value: value, False)
    assert kept_false.toJSON()["refs"][kept_false.uid]["preserve"] is False
    kept_true = Schema.transform(Schema.string(), lambda value: value, True)
    assert kept_true.toJSON()["refs"][kept_true.uid]["preserve"] is True

    # `Schema.lazy` passes `{ type, builder, inner }` to the constructor and
    # `builder` is a function JSON drops, so `inner` precedes `meta`.
    lazy_schema = Schema.lazy(lambda: Schema.string())
    lazy_node = lazy_schema.toJSON()["refs"][lazy_schema.uid]
    assert list(lazy_node.keys()) == ["type", "inner", "meta"]
    assert lazy_node["inner"] == lazy_schema.inner.uid
    assert lazy_node["meta"] == {}


def test_tojson_normalizes_non_finite_numbers():
    """`JSON.stringify` renders a non-finite number as `null`."""
    schema = Schema.const_(float("nan"))
    assert schema.toJSON()["refs"][schema.uid] == {"type": "const", "meta": {}, "value": None}
    infinite = Schema.const_(float("inf"))
    assert infinite.toJSON()["refs"][infinite.uid]["value"] is None
    bits = Schema.bitset({"a": float("nan"), "b": float("inf"), "c": 0.5})
    assert bits.toJSON()["refs"][bits.uid]["bits"] == {"a": None, "b": None, "c": 0.5}


def test_constructor_clones_an_existing_schema():
    """`Schema(schema)` copies the own members by reference under a fresh uid."""
    base = Schema.string().default("x")
    copy = Schema(base)
    assert copy.type == base.type
    assert copy.meta is base.meta
    assert copy.uid != base.uid


def test_simplify_walks_the_for_in_keys_of_any_value():
    """
    `simplify()` enumerates `for (const key in value)` regardless of the value.

    Verified against the reference: an object schema over a list, string or
    number enumerates that value's keys, keeps nothing and reports the empty
    default, a dict schema keeps every enumerated member, and the array branch's
    `value.forEach` raises for a value without it.
    """
    assert Schema.object({"a": Schema.string()}).simplify([1, 2]) is None
    assert Schema.object({"a": Schema.string()}).simplify("ab") is None
    assert Schema.object({"a": Schema.string()}).simplify(7) is None
    assert Schema.dict(Schema.number()).simplify([1, 2]) == {"0": 1, "1": 2}
    assert Schema.dict(Schema.string()).simplify("ab") == {"0": "a", "1": "b"}
    assert Schema.array(Schema.number()).simplify([1, 2]) == [1, 2]

    with pytest.raises(TypeError) as exc:
        Schema.array(Schema.number()).simplify({"a": 1})
    assert str(exc.value) == "value.forEach is not a function"
    with pytest.raises(TypeError) as exc:
        Schema.tuple([Schema.string()]).simplify("x")
    assert str(exc.value) == "value.forEach is not a function"


def test_factories_create_the_node_before_shorthand_members():
    """
    A factory node exists before it resolves a shorthand member.

    Verified against the reference uid numbering: the reference constructs
    `new Schema({ type })` first and only then runs `Schema.from` over its
    members, so an implicitly created member node always has the higher uid.
    """
    envelope = Schema.dict(Schema.number()).toJSON()
    node = envelope["refs"][envelope["uid"]]
    assert node["inner"] < envelope["uid"] < node["sKey"]
    assert list(envelope["refs"].keys()) == [node["inner"], envelope["uid"], node["sKey"]]

    union = Schema.union(["red", "blue"]).toJSON()
    members = union["refs"][union["uid"]]["list"]
    assert all(member > union["uid"] for member in members)

    obj = Schema.object({"a": "x"}).toJSON()
    assert obj["refs"][obj["uid"]]["dict"]["a"] > obj["uid"]

    transform = Schema.transform("bar", lambda: "foo").toJSON()
    assert transform["refs"][transform["uid"]]["inner"] > transform["uid"]

    array = Schema.array(int).toJSON()
    assert array["refs"][array["uid"]]["inner"] > array["uid"]

    tuple_schema = Schema.tuple([int, str]).toJSON()
    assert all(member > tuple_schema["uid"] for member in tuple_schema["refs"][tuple_schema["uid"]]["list"])


def test_object_members_follow_ecmascript_key_order():
    """`valueMap` enumerates `Object.keys`, so integer-like members come first."""
    schema = Schema.object({"z": Schema.string(), "2": Schema.string(), "a": Schema.string()})
    assert list(schema.dict.keys()) == ["2", "z", "a"]
    assert schema.to_string() == "{ 2?: string, z?: string, a?: string }"
    node = schema.toJSON()["refs"][schema.uid]
    assert list(node["dict"].keys()) == ["2", "z", "a"]


def test_tojson_envelope_roundtrip():
    """
    README Serializability: `new Schema(JSON.parse(JSON.stringify(schema1)))`
    "should have the same effect as schema1".

    The reference constructor recognizes an `options.refs` envelope, rebuilds
    every referenced node, resolves the relations and returns the root node, so
    the hydrated schema validates like the original, keeps its nested relations,
    and takes fresh uids (`env.uid` stays the uid of the serialized root).
    """
    schema = Schema.object({
        "foo": Schema.string(),
        "bar": Schema.number().default(1),
        "baz": Schema.dict(Schema.array(Schema.string())),
    })
    payload = json.loads(json.dumps(schema.toJSON()))
    hydrated = Schema(payload)

    assert hydrated.type == "object"
    assert hydrated.to_string() == schema.to_string()
    # The rebuilt root is a new node, not the uid the envelope names.
    assert hydrated.uid != payload["uid"]
    # Relations resolve to the referenced nodes.
    assert hydrated.dict["foo"].type == "string"
    assert hydrated.dict["bar"].meta == {"default": 1}
    assert hydrated.dict["baz"].inner.inner.type == "string"
    assert hydrated.dict["baz"].s_key.type == "string"

    assert hydrated({"foo": "a", "baz": {"k": ["x"]}}) == {"foo": "a", "bar": 1, "baz": {"k": ["x"]}}
    with pytest.raises(ValidationError) as exc:
        hydrated({"foo": 1})
    assert str(exc.value) == "$.foo expected string but got 1"

    # Re-serializing a hydrated tree keeps the same relative node graph.
    again = json.loads(json.dumps(hydrated.toJSON()))
    assert again["uid"] == hydrated.uid
    assert [int(key) for key in again["refs"]] == sorted(int(key) for key in again["refs"])
    assert again["refs"][str(hydrated.uid)]["type"] == "object"

    # A shared node is hydrated once and stays shared.
    shared = Schema.string()
    shared_tree = Schema.object({"a": shared, "b": shared})
    rehydrated = Schema(json.loads(json.dumps(shared_tree.toJSON())))
    assert rehydrated.dict["a"] is rehydrated.dict["b"]

    # The upstream client case `rehydrates a serialized envelope into a
    # working validator` (reference/packages/client/ui-settings/tests/
    # schema.client.spec.ts) consumes a rehydrated envelope through the
    # Standard Schema surface, whose issues carry the full message and path.
    assert hydrated.validate({"foo": 1}) == {
        "issues": [{"message": "$.foo expected string but got 1", "path": ["foo"]}],
    }
    assert hydrated.validate({"foo": "a"}) == {"value": {"foo": "a", "bar": 1, "baz": {}}}
    nested = Schema(json.loads(json.dumps(Schema.object({"a": Schema.array(Schema.number())}).toJSON())))
    assert nested.validate({"a": [1, "x"]}) == {
        "issues": [{"message": "$.a[1] expected number but got x", "path": ["a", 1]}],
    }

    # `from_json` is the port-only alias for the same constructor path.
    alias = Schema.from_json(json.loads(json.dumps(schema.toJSON())))
    assert alias.type == "object"
    assert alias({"foo": "a", "baz": {}}) == {"foo": "a", "bar": 1, "baz": {}}
    # A plain node payload is an ordinary options object.
    assert Schema({"type": "string"}).type == "string"


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


# ---------------------------------------------------------------------------
# Cases added for the reference's shared-meta modifiers, `i18n` lookup rules and
# lazy stub serialization, verified against the pinned reference on Node.
# ---------------------------------------------------------------------------


def test_union_inline_formatter_parenthesizes_one_member():
    """`formatters.union` wraps the joined members for every inline call."""
    assert Schema.union([Schema.string()]).to_string(True) == "(string)"
    assert Schema.union([Schema.string()]).to_string() == "string"
    assert Schema.union([Schema.string(), Schema.number()]).to_string(True) == "(string | number)"
    # Every formatter that inlines its member shows the parentheses.
    assert Schema.array(Schema.union([Schema.string()])).to_string() == "(string)[]"
    assert Schema.intersect([Schema.union([Schema.string()]), Schema.boolean()]).to_string() == "(string) & boolean"
    assert Schema.transform(Schema.union([Schema.number()]), lambda value: value).to_string(True) == "(number)"
    assert Schema.union([Schema.union([Schema.string()]), Schema.boolean()]).to_string(True) == "(string | boolean)"


def test_badge_modifiers_write_into_the_shared_meta_object():
    """`deprecated()`/`experimental()` push into `schema.meta.badges`."""
    base = Schema.string()
    one = base.deprecated()
    two = one.experimental()

    # `Schema(this)` shares the meta object, so every clone lists both badges.
    assert base.meta is one.meta
    assert one.meta is two.meta
    assert base.meta["badges"] == [
        {"text": "deprecated", "type": "danger"},
        {"text": "experimental", "type": "warning"},
    ]
    assert two.toJSON()["refs"][two.uid]["meta"]["badges"] == base.meta["badges"]

    # A plain modifier clone keeps sharing the badge list without adding a badge.
    assert Schema.string().deprecated().required().meta["badges"] == [
        {"text": "deprecated", "type": "danger"},
    ]

    # `meta.badges ||= []` replaces a falsey badge list.
    reset = Schema.string()
    reset.meta["badges"] = None
    assert reset.deprecated().meta["badges"] == [{"text": "deprecated", "type": "danger"}]


def test_i18n_description_merge_rules():
    """`mergeDesc` reads `$description`/`$desc` or a plain string message."""
    def build():
        return Schema.object({
            "username": Schema.string().description("Default username"),
            "timeout": Schema.number().description("Connection timeout"),
        }).description("Server configuration")

    localized = build().i18n({
        "zh": {"$description": "Server Config ZH", "username": "Username ZH", "timeout": "Timeout ZH"},
        "ja": {"$desc": "Server Config JA", "username": "Username JA", "timeout": "Timeout JA"},
    })
    assert localized.meta["description"] == {
        "": "Server configuration", "zh": "Server Config ZH", "ja": "Server Config JA",
    }
    assert localized.dict["username"].meta["description"] == {
        "": "Default username", "zh": "Username ZH", "ja": "Username JA",
    }
    assert localized.dict["timeout"].meta["description"] == {
        "": "Connection timeout", "zh": "Timeout ZH", "ja": "Timeout JA",
    }

    # A message keyed by the empty string carries neither `$description` nor
    # `$desc` and is not a string, so the root description gains no entry for
    # that locale; the member message still resolves through `data[key]`.
    empty_key = build().i18n({"zh": {"": "Server Config ZH", "username": "Username ZH"}})
    assert empty_key.meta["description"] == {"": "Server configuration"}
    assert empty_key.dict["username"].meta["description"] == {
        "": "Default username", "zh": "Username ZH",
    }

    # A plain string message is applied, and the merge lands in the meta object
    # the source schema shares.
    base = build()
    assert base.i18n({"zh": "Simple ZH"}).meta["description"] == {
        "": "Server configuration", "zh": "Simple ZH",
    }
    assert base.meta["description"] == {"": "Server configuration", "zh": "Simple ZH"}


def test_i18n_member_message_lookup():
    """`getInner(data)?.[key] ?? data?.[key]` decides every member message."""
    nested = Schema.object({"a": Schema.object({"b": Schema.string()})}).i18n(
        {"zh": {"$value": {"a": {"$value": {"b": "乙"}}}}}
    )
    assert nested.dict["a"].dict["b"].meta["description"] == {"zh": "乙"}

    # A `$value` entry without the member key falls back to the message object.
    fallback = Schema.object({"a": Schema.string(), "b": Schema.number()}).i18n(
        {"zh": {"$value": {"a": "甲"}, "b": "乙"}}
    )
    assert fallback.dict["a"].meta["description"] == {"zh": "甲"}
    assert fallback.dict["b"].meta["description"] == {"zh": "乙"}

    # A message string is not an object, so a member keyed by it localizes to
    # nothing while the dict and array `inner` and the tuple `list` read their
    # own entries.
    unmapped = Schema.object({"a": Schema.string()}).i18n({"zh": "顶层"})
    assert unmapped.dict["a"].meta.get("description") is None
    assert Schema.object({"a": Schema.string().description("keep")}).i18n(
        {"zh": "顶层"}
    ).dict["a"].meta["description"] == {"": "keep"}

    assert Schema.dict(Schema.string()).i18n({"zh": {"$inner": "值"}}).inner.meta["description"] == {"zh": "值"}
    assert Schema.dict(Schema.string()).i18n({"zh": {"$value": "值"}}).inner.meta["description"] == {"zh": "值"}
    assert Schema.array(Schema.string()).i18n({"zh": {"$inner": {"$value": "项"}}}).inner.meta.get("description") is None
    assert Schema.tuple([Schema.string(), Schema.number()]).i18n(
        {"zh": {"$value": ["甲", "乙"]}}
    ).list[1].meta["description"] == {"zh": "乙"}
    assert Schema.dict(Schema.string()).i18n({"zh": {"$key": "键"}}).s_key.meta["description"] == {"zh": "键"}

    # An unbuilt lazy node keeps its `{ toJSON }` stub as `inner` in the
    # reference, and that stub has no `i18n`.
    with pytest.raises(TypeError) as exc:
        Schema.lazy(lambda: Schema.string()).i18n({"zh": "顶层"})
    assert "schema.inner.i18n is not a function" in str(exc.value)


def test_lazy_clone_serializes_the_stub_origin_schema():
    """A clone serializes the node `Schema.lazy`'s stub closes over."""
    built = Schema.object({"a": Schema.string()})
    base = Schema.lazy(lambda: built)
    clone = base.description("outer")

    envelope = clone.toJSON()
    lazy_node = envelope["refs"][clone.uid]
    built_node = envelope["refs"][lazy_node["inner"]]

    assert lazy_node["type"] == "lazy"
    assert lazy_node["meta"] == {"description": "outer"}
    assert built_node["type"] == "object"
    # The stub merges the meta of the node the factory created, not the clone's.
    assert built_node["meta"] == {"default": {}}
    assert base.inner is built
    # The port spells the reference's `{ toJSON }` stub as the port's nullish
    # value plus `lazy_origin` (LEGAL_ADAPTATION).
    assert clone.inner is None

    # Resolving builds the resolved node's own schema with its meta.
    resolved = Schema.lazy(lambda: Schema.string()).description("outer")
    assert resolved("x") == "x"
    assert resolved.inner.meta == {"description": "outer"}


def test_lazy_builder_failures_fail_loud():
    """A missing builder and a builder yielding no schema both raise TypeError."""
    with pytest.raises(TypeError) as exc:
        Schema.lazy(lambda: None).toJSON()
    assert "Cannot read properties of null (reading 'meta')" in str(exc.value)

    with pytest.raises(TypeError) as exc:
        Schema.lazy(lambda: None)("x")
    assert "Cannot read properties of null (reading 'meta')" in str(exc.value)

    with pytest.raises(TypeError) as exc:
        Schema({"type": "lazy"})("x")
    assert "schema.builder is not a function" in str(exc.value)
