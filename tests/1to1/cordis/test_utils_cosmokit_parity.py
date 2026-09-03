"""
1:1 Test Parity for Cordis utils and Cosmokit
Authority:
- reference/vendor/cordis/src/utils.ts
- reference/vendor/cosmokit/src/{array,misc,string,time,types}.ts
"""

from collections import OrderedDict
import datetime
import re
import pytest

from dsh.cordis.utils import (
    camel_case,
    camelCase,
    param_case,
    paramCase,
    snake_case,
    snakeCase,
    Time,
    value_map,
    filter_keys,
    pick,
    omit,
    deep_equal,
    DisposableList,
    get_traceable,
    with_props,
    compose_error,
    build_outer_stack,
    is_object,
    contain,
    intersection,
    difference,
    union,
    deduplicate,
    remove,
    make_array,
    noop,
    is_non_nullable,
    is_plain_object,
    trim_slash,
    sanitize,
)
from dsh.cordis.plugin import Plugin


def test_d1_camel_case_digit_and_upper_after_delimiter():
    """ts:cosmokit/string.ts:12-14 - only lower-case characters following delimiter are converted."""
    assert camelCase("foo-1bar") == "foo-1bar"
    assert camelCase("foo-Foo") == "foo-Foo"
    assert camelCase("foo_bar") == "fooBar"
    assert camel_case("foo-bar-baz") == "fooBarBaz"


def test_d2_tokenize_acronym_and_spaces():
    """ts:cosmokit/string.ts:22-64 - tokenize preserves non-delim characters (spaces) and handles acronym boundaries."""
    assert paramCase("HTTPServer") == "http-server"
    assert snakeCase("HTTPServer") == "http_server"
    assert paramCase("fooBar baz") == "foo-bar baz"
    assert snakeCase("fooBar baz") == "foo_bar baz"


def test_d3_parse_time_unit_words_and_whitespace_rejection():
    """ts:cosmokit/time.ts:32-49 - full word units supported, whitespace strictly rejected."""
    assert Time.parse_time("1week") == 604800000
    assert Time.parse_time("1day") == 86400000
    assert Time.parse_time("2days") == 172800000
    assert Time.parse_time("1hour") == 3600000
    assert Time.parse_time("1min") == 60000
    assert Time.parse_time("1minute") == 60000
    assert Time.parse_time("1sec") == 1000
    assert Time.parse_time("1second") == 1000

    # Whitespace rejected
    assert Time.parse_time("10 s") == 0
    assert Time.parse_time(" 10s") == 0
    assert Time.parse_time("1w 2d") == 0


def test_d4_time_format_half_up_and_subseconds():
    """ts:cosmokit/time.ts:63-75 - Math.round half-up rounding and subsecond decimal retention."""
    assert Time.format(59500) == "1m"  # 59500ms >= minute - second/2 (59500ms), Math.round -> 1m
    assert Time.format(1500) == "2s"  # 1500ms Math.round -> 2s
    assert Time.format(-1500) == "-1s"  # -1.5s Math.round is -1
    assert Time.format(500.5) == "500.5ms"


def test_d5_time_missing_members():
    """ts:cosmokit/time.ts:10-30,51-91 - date numbers, template, toDigits."""
    assert Time.to_digits(5, 2) == "05"
    assert Time.to_digits(12, 2) == "12"

    d = datetime.datetime(2026, 9, 3, 14, 30, 45)
    formatted = Time.template("yyyy-MM-dd hh:mm:ss", d)
    assert formatted == "2026-09-03 14:30:45"

    parsed = Time.parse_date("10:30")
    assert isinstance(parsed, datetime.datetime)

    num = Time.get_date_number(d)
    recovered = Time.from_date_number(num)
    assert recovered.year == d.year and recovered.month == d.month and recovered.day == d.day


def test_d6_value_map_propagates_typeerror():
    """ts:cosmokit/misc.ts:44-46 - TypeError in transform function must propagate."""
    def bad_transform(v, k):
        return v + 1

    with pytest.raises(TypeError):
        value_map({"a": None}, bad_transform)


def test_d7_filter_keys_two_args_and_one_arg():
    """ts:cosmokit/misc.ts:39-41 - filterKeys passes (key, value) and supports single arg predicate."""
    data = {"a": 1, "b": 2, "c": 3}
    assert filter_keys(data, lambda k, v: v >= 2) == {"b": 2, "c": 3}
    assert filter_keys(data, lambda k: k == "a") == {"a": 1}


def test_d8_pick_omit_defaults_and_forced():
    """ts:cosmokit/misc.ts:52-69 - pick and omit with None keys return shallow copy, forced retains missing."""
    d = {"a": 1, "b": 2}
    assert pick(d) == {"a": 1, "b": 2}
    assert omit(d) == {"a": 1, "b": 2}

    picked_forced = pick(d, ["a", "c"], forced=True)
    assert "c" in picked_forced and picked_forced["a"] == 1


def test_d9_deep_equal_strict_and_patterns():
    """ts:cosmokit/types.ts:118-142 - strict parameter, distinct types, regex patterns, datetime."""
    assert deep_equal(1, True) is False
    assert deep_equal(1, 1.0) is True
    assert deep_equal({"a": 1}, OrderedDict([("a", 1)])) is True

    p1 = re.compile(r"abc", re.I)
    p2 = re.compile(r"abc", re.I)
    p3 = re.compile(r"abc")
    assert deep_equal(p1, p2) is True
    assert deep_equal(p1, p3) is False

    t1 = datetime.datetime(2026, 9, 3, 12, 0, 0)
    t2 = datetime.datetime(2026, 9, 3, 12, 0, 0)
    assert deep_equal(t1, t2) is True


def test_d10_disposable_list_identity_delete():
    """ts:cordis/utils.ts:21-25 - DisposableList delete removes the exact instance or matching bound method."""
    lst = DisposableList()
    t1 = (1, 2)
    t2 = (1, 2)
    lst.push(t1)
    lst.push(t2)

    assert lst.delete(t1) is True
    assert list(lst) == [t2]

    # Deleting value not in list returns False
    assert lst.delete((9, 9)) is False

    # Bound method identity
    class Cls:
        def disp(self):
            pass

    c = Cls()
    lst.push(c.disp)
    assert lst.delete(c.disp) is True


def test_d11_get_traceable_requires_tracker():
    """ts:cordis/utils.ts:117-125 - getTraceable without tracker returns original value."""
    class DummyCtx:
        pass

    ctx = DummyCtx()

    def normal_fn():
        return 42

    assert get_traceable(ctx, normal_fn) is normal_fn


def test_d12_with_props_overlay():
    """ts:cordis/utils.ts:128-140 - withProps creates overlay where props takes precedence."""
    class Target:
        def __init__(self):
            self.foo = "target_foo"
            self.bar = "target_bar"

    t = Target()
    p = with_props(t, {"foo": "overlay_foo"})
    assert p.foo == "overlay_foo"
    assert p.bar == "target_bar"


def test_d13_d14_compose_error_and_build_outer_stack():
    """ts:cordis/utils.ts:268-287 - composeError passes info dict with offset, build_outer_stack offset."""
    received_info = []

    def action(info):
        received_info.append(info)
        raise ValueError("test error")

    with pytest.raises(ValueError):
        compose_error(action)

    assert len(received_info) == 1
    assert "offset" in received_info[0]

    getter = build_outer_stack(offset=1)
    stack = getter()
    assert isinstance(stack, list)


def test_d15_is_object_slots_instance():
    """ts:cordis/utils.ts:102-104 - isObject returns True for __slots__ instance."""
    class SlotClass:
        __slots__ = ("a", "b")

        def __init__(self):
            self.a = 1
            self.b = 2

    assert is_object(SlotClass()) is True
    assert is_object(None) is False
    assert is_object(123) is False
    assert is_object("string") is False


def test_d16_cosmokit_array_helpers():
    """ts:cosmokit/array.ts:4-41 - contain, intersection, difference, union, deduplicate, remove, make_array."""
    assert contain([1, 2, 3], [2, 3]) is True
    assert contain([1, 2], [2, 3]) is False

    assert intersection([1, 2, 3], [2, 3, 4]) == [2, 3]
    assert difference([1, 2, 3], [2, 3, 4]) == [1]
    assert union([1, 2], [2, 3]) == [1, 2, 3]
    assert deduplicate([1, 2, 1, 3, 2]) == [1, 2, 3]

    arr = [1, 2, 3]
    assert remove(arr, 2) is True
    assert arr == [1, 3]
    assert remove(arr, 99) is False

    assert make_array(None) == []
    assert make_array(1) == [1]
    assert make_array([1, 2]) == [1, 2]


def test_d17_cosmokit_misc_helpers():
    """ts:cosmokit/misc.ts - noop, is_non_nullable, is_plain_object, trim_slash, sanitize."""
    assert noop() is None
    assert is_non_nullable(None) is False
    assert is_non_nullable(0) is True
    assert is_non_nullable("") is True

    assert is_plain_object({"a": 1}) is True
    assert is_plain_object([1, 2]) is False
    assert is_plain_object(None) is False

    assert trim_slash("/foo/bar/") == "foo/bar"
    assert trim_slash("///foo///") == "foo"
    assert sanitize("foo/../bar") == "bar"


def test_plugin_metadata_and_apply_signature():
    """ts:cordis/registry.ts:100-111 - Plugin base class metadata attributes and apply signature."""
    p = Plugin()
    assert hasattr(p, "provide")
    assert hasattr(p, "intercept")
    assert hasattr(p, "Config")

    # apply accepts config
    class SamplePlugin(Plugin):
        def apply(self, ctx, config=None):
            return "applied"

    sp = SamplePlugin()
    assert sp.apply(None, {"key": "val"}) == "applied"
