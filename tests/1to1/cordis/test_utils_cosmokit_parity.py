"""
1:1 parity suite for the vendored @deepseek-ai/cosmokit public contract.

Authoritative sources:
- reference/vendor/cosmokit/src/array.ts   (array set helpers)
- reference/vendor/cosmokit/src/misc.ts    (object / nullability helpers)
- reference/vendor/cosmokit/src/string.ts  (case, path, property formatting)
- reference/vendor/cosmokit/src/time.ts    (Time namespace)
- reference/vendor/cosmokit/src/types.ts   (is, Binary, clone, deepEqual)

The Python home of that contract is dsh/cordis/utils.py, which also carries the
reference/vendor/cordis/src/utils.ts cases (DisposableList, symbols, traceable
proxies, stack composition) that share the module.

Cases:
- C1..C7   array.ts: contain/intersection/difference/union/deduplicate/remove/makeArray
- C8..C17  misc.ts: noop/nullability/plain-object/filterKeys/mapValues/pick/omit/defineProperty
- C18..C24 string.ts: capitalize/camelCase/tokenize aliases/formatProperty/trimSlash/sanitize
- C25..C33 time.ts: constants/offset/parseTime/parseDate/format/toDigits/template/date numbers
- C45..C46 time.ts: zone-offset validation and the legacy/padded date grammar
- C34..C43 types.ts: is/Binary encodings/clone/deepEqual
- C47..C48 types.ts: clone leaf-branch freshness and deepEqual own-key strictness
- C44      exported-name surface of the reference package
- T1..T7   reference/vendor/cordis/src/utils.ts cases owned by the same module
"""

import calendar
import collections
import datetime
import json
import re
import time

import pytest

from dsh.cordis.utils import (
    Binary,
    DisposableList,
    Time,
    arrayBufferToBase64,
    arrayBufferToHex,
    base64ToArrayBuffer,
    build_outer_stack,
    camelCase,
    camel_case,
    camelize,
    capitalize,
    clone,
    compose_error,
    contain,
    deepEqual,
    deep_equal,
    deduplicate,
    defineProperty,
    define_property,
    difference,
    filterKeys,
    filter_keys,
    formatProperty,
    format_property,
    get_traceable,
    hexToArrayBuffer,
    hyphenate,
    intersection,
    is_,
    is_object,
    isNullable,
    isNonNullable,
    is_plain_object,
    isPlainObject,
    is_nullable,
    makeArray,
    make_array,
    mapValues,
    map_values,
    noop,
    omit,
    paramCase,
    param_case,
    pick,
    remove,
    sanitize,
    snakeCase,
    snake_case,
    trimSlash,
    trim_slash,
    uncapitalize,
    union,
    valueMap,
    value_map,
    with_props,
)
from dsh.cordis.plugin import Plugin


def _local_wall_clock(utc_seconds):
    """Local naive wall clock for a UTC instant, derived from the stdlib only."""
    stamp = time.localtime(utc_seconds)
    offset = -time.timezone + (3600 if stamp.tm_isdst > 0 else 0)
    return datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=utc_seconds + offset)


def _assert_now(value):
    """The port's `new Date()` fallback for an unrepresentable reference date.

    An ECMAScript Invalid Date has no Python value, and neither has a date
    the implementation-defined legacy parser produces from a two-digit year;
    both map onto the `new Date()` the reference uses for an empty input.
    """
    assert abs((value - datetime.datetime.now()).total_seconds()) < 5


# ---------------------------------------------------------------------------
# array.ts
# ---------------------------------------------------------------------------


def test_c1_contain_uses_includes_semantics():
    """array.ts:4-6 - `array2.every(item => array1.includes(item))`."""
    assert contain([1, 2, 3], [2, 3]) is True
    assert contain([1, 2], [2, 3]) is False
    # `every` over an empty array is true.
    assert contain([], []) is True
    assert contain([], [1]) is False
    # Array.prototype.includes is SameValueZero, not `===`-on-strings.
    assert contain([float('nan')], [float('nan')]) is True
    assert contain([1], ['1']) is False
    assert contain([1, 2], [1.0, 2.0]) is True
    # Duplicate membership still satisfies every().
    assert contain([1, 1], [1, 1]) is True


def test_c2_intersection_keeps_left_order_and_duplicates():
    """array.ts:9-11 - `array1.filter(item => array2.includes(item))`."""
    assert intersection([1, 2, 3], [2, 3, 4]) == [2, 3]
    assert intersection([3, 2, 1], [2, 3]) == [3, 2]
    assert intersection([1, 1, 2], [1]) == [1, 1]
    assert intersection([float('nan'), 1], [float('nan')])[0] != intersection([1], [1])[0]
    assert len(intersection([float('nan'), 1], [float('nan')])) == 1
    assert intersection([], [1]) == []


def test_c3_difference_keeps_left_order():
    """array.ts:14-16 - `array1.filter(item => !array2.includes(item))`."""
    assert difference([1, 2, 3], [2, 3, 4]) == [1]
    assert difference([3, 2, 1], [2]) == [3, 1]
    assert difference([1], ['1']) == [1]
    assert difference([float('nan')], [float('nan')]) == []


def test_c4_union_deduplicates_by_same_value_zero():
    """array.ts:19-21 - `Array.from(new Set([...array1, ...array2]))`."""
    assert union([1, 2], [2, 3]) == [1, 2, 3]
    assert union([1, 1, 2], [2, 1]) == [1, 2]
    # Set membership is SameValueZero: +0 and -0 collapse, NaN equals NaN.
    assert union([0], [-0.0]) == [0]
    union_nan = union([float('nan')], [float('nan')])
    assert len(union_nan) == 1
    left = {'n': 1}
    assert len(union([left], [left])) == 1
    assert len(union([{'n': 1}], [{'n': 1}])) == 2


def test_c5_deduplicate_keeps_first_occurrence():
    """array.ts:24-26 - `[...new Set(array)]`."""
    assert deduplicate([1, 2, 1, 3, 2]) == [1, 2, 3]
    assert deduplicate(['a', 'a', 'b']) == ['a', 'b']
    assert deduplicate([0, -0.0]) == [0]
    assert len(deduplicate([float('nan'), float('nan')])) == 1
    shared = {'n': 1}
    assert len(deduplicate([shared, shared, {'n': 1}])) == 2


def test_c6_remove_uses_index_of_and_mutates_in_place():
    """array.ts:29-38 - `list?.indexOf(item)` (===) with splice."""
    values = [1, 2, 3]
    assert remove(values, 2) is True
    assert values == [1, 3]
    # Only the first match is removed.
    values = [1, 2, 2]
    assert remove(values, 2) is True
    assert values == [1, 2]
    assert remove(values, 9) is False
    # `list?.` tolerates a nullish list.
    assert remove(None, 1) is False
    # indexOf uses ===, so a bool never matches a number and vice versa.
    values = [1]
    assert remove(values, True) is False
    assert values == [1]
    values = ['1']
    assert remove(values, 1) is False
    # 0 and -0 ARE the same value under ===.
    values = [0]
    assert remove(values, -0.0) is True
    assert values == []


def test_c7_make_array_wraps_non_arrays():
    """array.ts:40-42 - `Array.isArray(source) ? source : isNullable(source) ? [] : [source]`."""
    assert makeArray(None) == []
    assert makeArray(0) == [0]
    assert makeArray('') == ['']
    assert makeArray(False) == [False]
    assert makeArray({'a': 1}) == [{'a': 1}]
    values = [1, 2]
    assert makeArray(values) is values
    assert makeArray([]) == []


# ---------------------------------------------------------------------------
# misc.ts
# ---------------------------------------------------------------------------


def test_c8_noop_returns_none():
    """misc.ts:17 - `noop()` is an empty body: undefined."""
    assert noop() is None
    assert noop(1, 2, key='value') is None


def test_c9_nullability_helpers():
    """misc.ts:20-28 - isNullable is `value === null || value === undefined`."""
    assert is_nullable(None) is True
    assert isNullable(None) is True
    assert is_nullable(0) is False
    assert is_nullable('') is False
    assert is_nullable(False) is False
    assert is_nullable(float('nan')) is False
    assert isNonNullable(None) is False
    assert isNonNullable(0) is True
    assert isNonNullable('') is True


def test_c10_is_plain_object_accepts_every_non_array_object():
    """misc.ts:30-32 - `data && typeof data === 'object' && !Array.isArray(data)`."""
    assert is_plain_object({'a': 1}) is True
    assert isPlainObject({}) is True
    assert is_plain_object(datetime.datetime(2026, 9, 3)) is True
    assert is_plain_object(re.compile('a')) is True
    assert is_plain_object({'a'}) is True
    # Falsy operands and non-objects return falsy.
    assert is_plain_object(None) is False
    assert is_plain_object(0) is False
    assert is_plain_object('') is False
    assert is_plain_object(False) is False
    assert is_plain_object([]) is False
    assert is_plain_object(lambda: 1) is False


def test_c11_filter_keys_passes_key_then_value():
    """misc.ts:39-41 - `Object.entries(object).filter(([key, value]) => filter(key, value))`."""
    data = {'a': 1, 'b': 2, 'c': 3}
    assert filter_keys(data, lambda k, v: v >= 2) == {'b': 2, 'c': 3}
    assert filterKeys(data, lambda k: k == 'a') == {'a': 1}
    assert filter_keys({}, lambda k, v: True) == {}
    # A new object is returned; the source is untouched.
    result = filter_keys(data, lambda k, v: True)
    assert result == data
    assert result is not data
    assert list(filter_keys({'b': 1, 'a': 2}, lambda k, v: True)) == ['b', 'a']


def test_c12_map_values_passes_value_then_key():
    """misc.ts:44-47 - `Object.entries(object).map(([key, value]) => [key, transform(value, key)])`."""
    assert map_values({'a': 1, 'b': 2}, lambda v, k: str(v) + k) == {'a': '1a', 'b': '2b'}
    assert mapValues({'a': 1}, lambda v: v * 2) == {'a': 2}
    assert list(mapValues({'b': 1, 'a': 2}, lambda v: v)) == ['b', 'a']
    source = {'a': 1}
    assert map_values(source, lambda v: v) is not source

    def boom(value):
        raise ValueError('boom')

    with pytest.raises(ValueError, match='boom'):
        map_values({'a': 1}, boom)


def test_c13_value_map_aliases_are_the_same_function():
    """misc.ts:49 - `export { mapValues as valueMap }`."""
    assert valueMap is map_values
    assert value_map is map_values
    assert mapValues is map_values
    assert valueMap({'a': 1}, lambda v: v + 1) == {'a': 2}


def test_c14_pick_copies_or_selects_keys():
    """misc.ts:52-60 - `!keys` copies the object, otherwise undefined values are dropped."""
    source = {'a': 1, 'b': 2}
    assert pick(source) == {'a': 1, 'b': 2}
    assert pick(source) is not source
    assert pick(source, ['a']) == {'a': 1}
    # A missing key reads as undefined and is dropped.
    assert pick(source, ['a', 'c']) == {'a': 1}
    # `forced` keeps the key even when it reads as undefined.
    assert pick(source, ['a', 'c'], True) == {'a': 1, 'c': None}
    # An empty key list is not the `!keys` fast path: it selects nothing.
    assert pick(source, []) == {}
    # A present null value is not undefined, so it is kept.
    assert pick({'a': None, 'b': 2}, ['a', 'b']) == {'a': None, 'b': 2}
    assert pick(source, ['a'], True) == {'a': 1}
    assert source == {'a': 1, 'b': 2}


def test_c15_omit_deletes_keys():
    """misc.ts:62-70 - shallow copy then `Reflect.deleteProperty` per key."""
    source = {'a': 1, 'b': 2}
    assert omit(source) == {'a': 1, 'b': 2}
    assert omit(source) is not source
    assert omit(source, ['a']) == {'b': 2}
    assert omit(source, []) == {'a': 1, 'b': 2}
    assert omit(source, ['z']) == {'a': 1, 'b': 2}
    assert source == {'a': 1, 'b': 2}


def test_c16_define_property_returns_the_target():
    """misc.ts:76-78 - Object.defineProperty(object, key, { writable: true, value })."""
    target = {}
    assert define_property(target, 'k', 5) is target
    assert target['k'] == 5
    target = {'k': 1}
    assert defineProperty(target, 'k', 2) == {'k': 2}


def test_c17_export_aliases_of_misc_helpers():
    """misc.ts:20-78 - every exported name resolves to the same behaviour."""
    assert isNullable is is_nullable
    assert isNonNullable is not None
    assert isPlainObject is is_plain_object
    assert filterKeys is filter_keys
    assert defineProperty is define_property


# ---------------------------------------------------------------------------
# string.ts
# ---------------------------------------------------------------------------


def test_c18_capitalize_uncapitalize_use_char_at():
    """string.ts:2-10 - `source.charAt(0).toUpperCase() + source.slice(1)`."""
    assert capitalize('foo') == 'Foo'
    assert capitalize('FOO') == 'FOO'
    assert capitalize('') == ''
    assert capitalize('1abc') == '1abc'
    assert uncapitalize('FOO') == 'fOO'
    assert uncapitalize('foo') == 'foo'
    assert uncapitalize('') == ''


def test_c19_camel_case_only_folds_lowercase_after_a_delimiter():
    """string.ts:12-14 - `/[_-][a-z]/g` replacement."""
    assert camelCase('foo-bar') == 'fooBar'
    assert camelCase('foo_bar') == 'fooBar'
    assert camel_case('a_b_c') == 'aBC'
    assert camelCase('') == ''
    # A digit or an uppercase letter after the delimiter is left alone.
    assert camelCase('foo-1bar') == 'foo-1bar'
    assert camelCase('foo-Foo') == 'foo-Foo'
    assert camelCase('foo-') == 'foo-'
    assert camelize is camel_case


def test_c20_param_case_tokens_camel_and_acronym_boundaries():
    """string.ts:19-64 - the DELIM/UPPER/LOWER tokenizer with an acronym lookahead."""
    assert paramCase('fooBar') == 'foo-bar'
    assert param_case('foo_bar_baz') == 'foo-bar-baz'
    assert paramCase('HTTPServer') == 'http-server'
    assert paramCase('ABc') == 'a-bc'
    assert paramCase('ABC') == 'abc'
    assert paramCase('FooBar') == 'foo-bar'
    assert paramCase('foo2Bar') == 'foo2-bar'
    assert paramCase('_fooBar') == 'foo-bar'
    assert paramCase('fooBar_') == 'foo-bar-'
    assert paramCase('a--b') == 'a-b'
    # Only the delimiter and underscore are delimiters; other characters pass through.
    assert paramCase('fooBar baz') == 'foo-bar baz'
    assert paramCase('a.b') == 'a.b'
    assert paramCase('123') == '123'
    assert paramCase('') == ''


def test_c21_snake_case_and_token_aliases():
    """string.ts:57-69 - paramCase/hyphenate and snakeCase share one tokenizer."""
    assert snakeCase('fooBar') == 'foo_bar'
    assert snake_case('foo-bar-baz') == 'foo_bar_baz'
    assert snakeCase('HTTPServer') == 'http_server'
    assert hyphenate is param_case
    assert hyphenate('fooBar') == 'foo-bar'


def test_c22_format_property_matches_member_access_and_json_quoting():
    """string.ts:99-103 - identifier regex plus JSON.stringify for the bracket form."""
    assert formatProperty('foo') == '.foo'
    assert format_property('$a') == '.$a'
    assert format_property('_a') == '._a'
    assert format_property('foo-bar') == '["foo-bar"]'
    assert format_property('1') == '["1"]'
    assert format_property('') == '[""]'
    assert format_property('a b') == '["a b"]'
    assert format_property('a"b') == '["a\\"b"]'
    assert format_property('a\nb') == '["a\\nb"]'
    # `\w` is ASCII-only without the /u flag, so non-ASCII identifiers bracket.
    assert format_property('\u00e9') == '["\u00e9"]'
    assert format_property('a\u00e9') == '["a\u00e9"]'
    # Non-string keys use `key.toString()`.
    assert format_property(0) == '[0]'
    assert format_property(-1.5) == '[-1.5]'
    assert format_property(True) == '[true]'


def test_c23_trim_slash_removes_one_trailing_slash():
    """string.ts:105-107 - `source.replace(/\\/$/, '')`."""
    assert trimSlash('/foo/bar/') == '/foo/bar'
    assert trim_slash('///foo///') == '///foo//'
    assert trim_slash('foo/bar') == 'foo/bar'
    assert trim_slash('/') == ''
    assert trim_slash('') == ''
    # ECMAScript `$` without /m does not match before a trailing newline.
    assert trim_slash('foo/\n') == 'foo/\n'


def test_c24_sanitize_prefixes_then_trims():
    """string.ts:110-113 - ensure a leading slash, then one trailing-slash trim."""
    assert sanitize('foo/bar/') == '/foo/bar'
    assert sanitize('/foo/bar') == '/foo/bar'
    assert sanitize('/foo/') == '/foo'
    assert sanitize('/') == ''
    assert sanitize('') == ''


# ---------------------------------------------------------------------------
# time.ts
# ---------------------------------------------------------------------------


def test_c25_time_constants():
    """time.ts:3-8 - millisecond/second/minute/hour/day/week."""
    assert Time.millisecond == 1
    assert Time.second == 1000
    assert Time.minute == 60000
    assert Time.hour == 3600000
    assert Time.day == 86400000
    assert Time.week == 604800000


def test_c26_timezone_offset_round_trip():
    """time.ts:10-18 - the module-level offset defaults to getTimezoneOffset()."""
    original = Time.get_timezone_offset()
    assert Time.getTimezoneOffset() == original
    assert isinstance(original, int)
    # `new Date().getTimezoneOffset()` is the local offset in minutes west of
    # UTC in the current DST state, which the local wall clock minus UTC is;
    # it is never a silent UTC (0) default on a host without `tm_gmtoff`.
    local_offset = datetime.datetime.now() - datetime.datetime.utcnow()
    assert original == -int(round(local_offset.total_seconds()) / 60)
    try:
        Time.set_timezone_offset(-480)
        assert Time.get_timezone_offset() == -480
        Time.setTimezoneOffset(60)
        assert Time.getTimezoneOffset() == 60
    finally:
        Time.set_timezone_offset(original)
    assert Time.get_timezone_offset() == original


def test_c27_parse_time_units_and_strict_anchoring():
    """time.ts:32-49 - the anchored unit regex and `parseFloat(x) * unit || 0`."""
    assert Time.parse_time('10s') == 10000
    assert Time.parseTime('5m') == 300000
    assert Time.parse_time('1h') == 3600000
    assert Time.parse_time('1d') == 86400000
    assert Time.parse_time('1w') == 604800000
    assert Time.parse_time('1w2d3h4m5s') == 604800000 + 172800000 + 10800000 + 240000 + 5000
    # Every unit accepts its full and plural word spellings.
    assert Time.parse_time('1week') == 604800000
    assert Time.parse_time('2days') == 172800000
    assert Time.parse_time('1hour') == 3600000
    assert Time.parse_time('1minute') == 60000
    assert Time.parse_time('1second') == 1000
    assert Time.parse_time('3secs') == 3000
    assert Time.parse_time('2mins') == 120000
    assert Time.parse_time('1.5s') == 1500
    assert Time.parse_time('0.5h') == 1800000
    # Anchored: no surrounding whitespace, no bare numbers, no suffix leftovers.
    assert Time.parse_time('10 s') == 0
    assert Time.parse_time(' 10s') == 0
    assert Time.parse_time('10s ') == 0
    assert Time.parse_time('1w 2d') == 0
    assert Time.parse_time('abc') == 0
    assert Time.parse_time('10') == 0
    assert Time.parse_time('1m5') == 0
    assert Time.parse_time('10S') == 0
    # ECMAScript `$` without /m and ASCII `\d`: a trailing newline or a
    # non-ASCII digit is not a match.
    assert Time.parse_time('10\ns') == 0
    assert Time.parse_time('1s\r\n') == 0
    assert Time.parse_time('\u0661\u0660s') == 0
    assert Time.parse_time('\uff11\uff10s') == 0
    assert Time.parse_time('') == 0
    assert Time.parse_time('0s') == 0


def test_c28_parse_date_time_only_forms_use_today():
    """time.ts:51-61 - `toLocaleDateString() + '-' + date` then `new Date(date)`."""
    now = datetime.datetime.now()
    result = Time.parseDate('10:30')
    assert (result.year, result.month, result.day) == (now.year, now.month, now.day)
    assert (result.hour, result.minute, result.second, result.microsecond) == (10, 30, 0, 0)
    result = Time.parse_date('10:30:45')
    assert (result.hour, result.minute, result.second) == (10, 30, 45)
    # 24:00 is a reachable clock value and lands on the next midnight.
    result = Time.parseDate('24:00')
    assert (result.hour, result.minute) == (0, 0)
    assert result.date() == (now + datetime.timedelta(days=1)).date()


def test_c29_parse_date_month_day_form_uses_the_current_year():
    """time.ts:55-57 - `getFullYear() + '-' + date` for `M-D-H:M`."""
    now = datetime.datetime.now()
    result = Time.parseDate('9-3-14:30')
    assert (result.year, result.month, result.day) == (now.year, 9, 3)
    assert (result.hour, result.minute, result.second) == (14, 30, 0)


def test_c30_parse_date_iso_forms():
    """time.ts:51-61 -> `new Date(string)`; ECMA-262 Date Time String Format."""
    # Date-only forms are UTC.
    assert Time.parseDate('2026-09-03') == _local_wall_clock(calendar.timegm((2026, 9, 3, 0, 0, 0)))
    assert Time.parseDate('2026-09') == _local_wall_clock(calendar.timegm((2026, 9, 1, 0, 0, 0)))
    assert Time.parseDate('2026') == _local_wall_clock(calendar.timegm((2026, 1, 1, 0, 0, 0)))
    # An explicit `Z` is the absent-offset default, not a numeric offset.
    assert Time.parseDate('2026-09-03Z') == _local_wall_clock(calendar.timegm((2026, 9, 3, 0, 0, 0)))
    # Date-time forms without an offset are local wall clock.
    assert Time.parseDate('2026-09-03T14:30') == datetime.datetime(2026, 9, 3, 14, 30)
    assert Time.parseDate('2026-09-03 14:30:45') == datetime.datetime(2026, 9, 3, 14, 30, 45)
    assert Time.parseDate('2026-09-03t14:30:45z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 14, 30, 45)))
    # A missing month/day part defaults to the first of its parent.
    assert Time.parseDate('2026T14:30') == datetime.datetime(2026, 1, 1, 14, 30)
    assert Time.parseDate('2026-09T14:30') == datetime.datetime(2026, 9, 1, 14, 30)
    # Explicit offsets shift the instant.
    assert Time.parseDate('2026-09-03T14:30:45Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 14, 30, 45)))
    assert Time.parseDate('2026-09-03T14:30:45+02:00') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 12, 30, 45)))
    assert Time.parseDate('2026-09-03T14:30+0200') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 12, 30, 0)))
    # A `Date` has millisecond resolution: extra fraction digits truncate.
    assert Time.parseDate('2026-09-03T14:30:45.123') == datetime.datetime(2026, 9, 3, 14, 30, 45, 123000)
    assert Time.parseDate('2026-09-03T14:30:45.5Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 14, 30, 45))) + datetime.timedelta(milliseconds=500)
    # `microsecond=123456` would keep sub-millisecond precision the reference drops.
    assert Time.parseDate('2026-09-03T14:30:45.123456789') == datetime.datetime(
        2026, 9, 3, 14, 30, 45, 123000)
    assert Time.parseDate('2026-09-03T14:30:45.999999999Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 14, 30, 45))) + datetime.timedelta(milliseconds=999)
    # `24:00:00` rolls into the next day; an out-of-range day rolls forward too.
    assert Time.parseDate('2026-09-03T24:00:00') == datetime.datetime(2026, 9, 4)
    assert Time.parseDate('2026-02-30') == _local_wall_clock(calendar.timegm((2026, 3, 2, 0, 0, 0)))
    # The unambiguous legacy forms are local wall clock.
    assert Time.parseDate('2026-9-3') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate('2026/09/03') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate('09/03/2026') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate('9/3/2026 14:30') == datetime.datetime(2026, 9, 3, 14, 30)
    # Relative time strings are `Date.now() + parsed`.
    delta = Time.parseDate('1h') - datetime.datetime.now()
    assert abs(delta - datetime.timedelta(hours=1)) < datetime.timedelta(seconds=5)


def test_c31_parse_date_unrepresentable_inputs_fall_back_to_now():
    """time.ts:61 - the reference returns `new Date(date)`, here `new Date()`.

    LEGAL_ADAPTATION: an ECMAScript Invalid Date has no Python value, so every
    input the reference rejects maps to the same `new Date()` an empty string
    produces. Each assertion below is an Invalid Date on the reference side.
    """
    _assert_now(Time.parseDate(''))
    _assert_now(Time.parseDate('not a date'))
    _assert_now(Time.parseDate('2026-13-01'))
    _assert_now(Time.parseDate('2026-09-32'))
    _assert_now(Time.parseDate('2026-09-03T25:00'))
    _assert_now(Time.parseDate('13:99'))
    _assert_now(Time.parseDate('2026-09-03+02:00'))
    _assert_now(Time.parseDate('2026-09-03T14:30:60Z'))
    # A time-only string is not an Invalid Date; it is today at that clock time.
    assert Time.parseDate('14:30').hour == 14


def test_c45_parse_date_rejects_malformed_zone_offsets():
    """time.ts:51-61 - an out-of-range zone offset is an Invalid Date.

    Reference behavior read from the pinned source on Node 22
    (`new Date(string)`): hours are 00-23, minutes 00-59, only `Z` may
    follow a date with no clock time, and a numeric offset must keep the
    `+HH:MM` / `+HHMM` shape.
    """
    _assert_now(Time.parseDate('2026-09-03T14:30+24:00'))
    _assert_now(Time.parseDate('2026-09-03T14:30-24:00'))
    _assert_now(Time.parseDate('2026-09-03T14:30+00:60'))
    _assert_now(Time.parseDate('2026-09-03T14:30+02:99'))
    _assert_now(Time.parseDate('2026-09-03T14:30+99:99'))
    _assert_now(Time.parseDate('2026-09-03T14:30+0260'))
    _assert_now(Time.parseDate('2026-09-03T14:30+02:00:00'))
    _assert_now(Time.parseDate('2026-09-03T14:30+02'))
    _assert_now(Time.parseDate('2026-09-03T14:30+02:'))
    _assert_now(Time.parseDate('2026-09-03+02:00'))
    _assert_now(Time.parseDate('2026-09-03+0200'))
    _assert_now(Time.parseDate('2026-9-3+02:00'))
    # The boundary values are accepted and normalize the instant.
    assert Time.parseDate('2026-09-03T14:30+23:59') == _local_wall_clock(
        calendar.timegm((2026, 9, 2, 14, 31, 0)))
    assert Time.parseDate('2026-09-03T14:30-00:00') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 14, 30, 0)))
    assert Time.parseDate('2026-09-03T14:30+0230') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 12, 0, 0)))
    assert Time.parseDate('2026-09-03T14:30-0130') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 16, 0, 0)))


def test_c46_parse_date_legacy_and_padded_forms():
    """time.ts:51-61 - the legacy forms `new Date(string)` resolves locally.

    The non-ISO grammar is implementation defined; every value below is the
    one the pinned reference produces on Node 22.  `T` belongs to the Date
    Time String Format only, V8 trims a padded string and then reads the
    trimmed form as local wall clock, and the two-digit-year / time-only
    heuristics stay unrepresentable (documented LEGAL_ADAPTATION).
    """
    # `YYYY[-M[-D]]`, `YYYY/MM[/DD]` and `M/D/YYYY` are local wall clock.
    assert Time.parseDate('2026-9') == datetime.datetime(2026, 9, 1)
    assert Time.parseDate('2026/9') == datetime.datetime(2026, 9, 1)
    assert Time.parseDate('2026/09') == datetime.datetime(2026, 9, 1)
    assert Time.parseDate('2026-9/3') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate('2026-09/03') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate('2026-1-3') == datetime.datetime(2026, 1, 3)
    assert Time.parseDate('1/3/2026') == datetime.datetime(2026, 1, 3)
    assert Time.parseDate('2026-9 12:30') == datetime.datetime(2026, 9, 1, 12, 30)
    assert Time.parseDate('2026-9-3 12:30:45') == datetime.datetime(2026, 9, 3, 12, 30, 45)
    assert Time.parseDate('2026-9-3 12:30:45.5') == datetime.datetime(2026, 9, 3, 12, 30, 45, 500000)
    # Repeated whitespace is accepted between the date and the clock time.
    assert Time.parseDate('2026-9-3  12:30') == datetime.datetime(2026, 9, 3, 12, 30)
    assert Time.parseDate('2026-09-03\t12:30') == datetime.datetime(2026, 9, 3, 12, 30)
    # A zone suffix on a legacy form shifts the wall clock like an ISO one,
    # and `Z` may also follow a legacy date that has no clock time.
    assert Time.parseDate('2026-9-3 12:30Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 12, 30, 0)))
    assert Time.parseDate('2026-9-3 12:30 Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 12, 30, 0)))
    assert Time.parseDate('2026-9-3 12:30 +02:00') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 10, 30, 0)))
    assert Time.parseDate('2026/9/3Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 0, 0, 0)))
    assert Time.parseDate('2026-9Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 1, 0, 0, 0)))
    assert Time.parseDate('2026-09-03 Z') == _local_wall_clock(
        calendar.timegm((2026, 9, 3, 0, 0, 0)))
    # Only a space (never `T`) separates these forms from their clock time.
    _assert_now(Time.parseDate('2026-9-3T12:30'))
    _assert_now(Time.parseDate('2026-9-3t12:30'))
    _assert_now(Time.parseDate('2026/9/3T12:30'))
    _assert_now(Time.parseDate('1/3/2026T12:30'))
    _assert_now(Time.parseDate('2026-9-3 12:30.5'))
    _assert_now(Time.parseDate('2026-9-3 +02:00'))
    _assert_now(Time.parseDate('2026-9-3 12:30:60'))
    # A padded string is read through the trimmed form, which is local wall
    # clock even where the unpadded Date Time String Format is UTC.
    assert Time.parseDate('2026-09') == _local_wall_clock(
        calendar.timegm((2026, 9, 1, 0, 0, 0)))
    assert Time.parseDate('2026-09\n') == datetime.datetime(2026, 9, 1)
    assert Time.parseDate('2026-09-03 ') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate(' 2026-09-03') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate('\t2026-09-03') == datetime.datetime(2026, 9, 3)
    assert Time.parseDate('2026-9-3 12:30 \n') == datetime.datetime(2026, 9, 3, 12, 30)
    assert Time.parseDate('2026 ') == datetime.datetime(2026, 1, 1)
    # Padding does not rescue a form whose own grammar V8 rejects.
    _assert_now(Time.parseDate('2026-09-03T14:30\n'))
    _assert_now(Time.parseDate('2026-09-03T14:30Z\n'))
    _assert_now(Time.parseDate('14:30\n'))
    # The reference loses its own regex match on a padded M-D-H:MM string
    # and reads it as a two-digit year instead ('9-9-12:30 ' is 2001-09-09
    # on V8), which stays unrepresentable and reports as now.
    _assert_now(Time.parseDate('9-9-12:30\n'))


def test_c32_format_rounds_half_up_with_unit_thresholds():
    """time.ts:63-75 - `Math.round` against day/hour/minute/second thresholds."""
    assert Time.format(0) == '0ms'
    assert Time.format(500) == '500ms'
    assert Time.format(999) == '999ms'
    assert Time.format(-500) == '-500ms'
    # Math.round is floor(x + 0.5), so -1.5 rounds to -1.
    assert Time.format(1500) == '2s'
    assert Time.format(2500) == '3s'
    assert Time.format(-1500) == '-1s'
    assert Time.format(-2500) == '-2s'
    assert Time.format(59500) == '1m'
    assert Time.format(59499) == '59s'
    assert Time.format(120000) == '2m'
    assert Time.format(3570000) == '1h'
    assert Time.format(3569999) == '59m'
    assert Time.format(7200000) == '2h'
    assert Time.format(85800000) == '1d'
    assert Time.format(594999) == '10m'
    assert Time.format(85799999) == '1d'
    assert Time.format(172800000) == '2d'
    # Sub-second values render through Number.prototype.toString.
    assert Time.format(500.5) == '500.5ms'
    assert Time.format(1.25) == '1.25ms'
    assert Time.format(float('nan')) == 'NaNms'


def test_c33_to_digits_pads_the_rendered_number():
    """time.ts:77-79 - `source.toString().padStart(length, '0')`."""
    assert Time.toDigits(5) == '05'
    assert Time.toDigits(12) == '12'
    assert Time.toDigits(123, 2) == '123'
    assert Time.toDigits(0, 3) == '000'
    # padStart pads before the sign, not after it.
    assert Time.to_digits(-5, 3) == '0-5'
    # toString of a fraction keeps the fraction.
    assert Time.to_digits(1.5) == '1.5'
    assert Time.to_digits(1.5, 6) == '0001.5'


def test_c34_template_replaces_the_first_occurrence_of_each_token():
    """time.ts:81-91 - chained single-occurrence String.replace calls."""
    moment = datetime.datetime(2026, 9, 3, 14, 30, 45, 123000)
    assert Time.template('yyyy-MM-dd hh:mm:ss', moment) == '2026-09-03 14:30:45'
    assert Time.template('yy/MM/dd', moment) == '26/09/03'
    assert Time.template('SSS', moment) == '123'
    # `yyyy` is replaced before `yy`, each only once.
    # The `yy` pass then folds the first two characters of the leftover token.
    assert Time.template('yyyy-yyyy', moment) == '2026-26yy'
    assert Time.template('no tokens', moment) == 'no tokens'


def test_c35_date_numbers_use_the_supplied_offset():
    """time.ts:20-30 - getDateNumber/fromDateNumber over a minute-based offset."""
    moment = datetime.datetime(2026, 9, 3, 14, 30, 45)
    assert Time.getDateNumber(moment, 0) == int(
        (calendar.timegm((2026, 9, 3, 14, 30, 45)) / 60) // 1440)
    assert Time.getDateNumber(moment, -480) == int(
        (calendar.timegm((2026, 9, 3, 14, 30, 45)) / 60 + 480) // 1440)
    number = Time.getDateNumber(moment, -480)
    restored = Time.from_date_number(number, -480)
    assert (restored.year, restored.month, restored.day) == (2026, 9, 3)
    assert Time.fromDateNumber(number, -480) == restored
    # fromDateNumber builds `value * day + offset * minute` milliseconds.
    assert Time.from_date_number(0, 480) == _local_wall_clock(28800)
    assert Time.getDateNumber(0, 0) == 0


# ---------------------------------------------------------------------------
# types.ts
# ---------------------------------------------------------------------------


def test_c36_is_matches_constructor_or_internal_tag():
    """types.ts:8-22 - `value instanceof globalThis[type] || tag === type`."""
    assert is_('String', 'a') is True
    assert is_('String', ['a']) is False
    assert is_('Number', 1) is True
    assert is_('Number', '1') is False
    assert is_('Boolean', True) is True
    assert is_('Array', []) is True
    assert is_('Array', 'abc') is False
    # `[] instanceof Object` is true even though Array.isArray distinguishes it.
    assert is_('Object', []) is True
    assert is_('Object', {'a': 1}) is True
    assert is_('Object', lambda: 1) is True
    assert is_('Object', None) is False
    assert is_('Object', 1) is False
    assert is_('Date', datetime.datetime.now()) is True
    assert is_('RegExp', re.compile('a')) is True
    assert is_('Null', None) is True
    assert is_('Undefined', None) is True
    assert is_('Function', lambda: 1) is True
    assert is_('Set', {1, 2}) is True
    assert is_('ArrayBuffer', b'\x01\x02') is True
    assert is_('SharedArrayBuffer', bytearray(b'\x01\x02')) is True
    # `isArrayBufferLike` only matches a buffer that owns its memory;
    # `is('ArrayBuffer', new Uint8Array(2))` is false in the reference.
    assert is_('ArrayBuffer', memoryview(b'\x01\x02')) is False
    # `ArrayBuffer.isView` is the other half of the split, so a buffer is
    # not a view (`is('Uint8Array', new ArrayBuffer(2))` is false).
    assert is_('Uint8Array', b'\x01\x02') is False
    assert is_('Uint8Array', memoryview(b'\x01\x02')) is True
    assert is_('DataView', memoryview(b'\x01\x02')) is True
    assert is_('Uint8Array', 'abc') is False
    assert is_('Error', ValueError('x')) is True
    # An unknown global name cannot match.
    assert is_('Widget', {'a': 1}) is False
    # One-argument form is a predicate factory.
    predicate = is_('String')
    assert predicate('a') is True
    assert predicate(1) is False


def test_c37_binary_source_detection_and_slicing():
    """types.ts:19-40 - is/isSource/fromSource."""
    # `is` is a Python keyword, so the reference attribute is read by name.
    binary_is = getattr(Binary, 'is')
    assert binary_is(b'\x01\x02') is True
    assert binary_is(bytearray(b'\x01\x02')) is True
    # A view is not a buffer, but it is an ArrayBuffer source.
    assert binary_is(memoryview(b'\x01\x02')) is False
    assert Binary.is_source(memoryview(b'\x01\x02')) is True
    assert Binary.isSource(b'\x01\x02') is True
    assert Binary.isSource(bytearray(b'\x01\x02')) is True
    assert Binary.isSource('abc') is False
    buffer = b'\x01\x02\x03\x04'
    assert Binary.from_source(buffer) is buffer
    # A view is narrowed to its own byte range.
    assert bytes(Binary.fromSource(memoryview(buffer)[1:3])) == b'\x02\x03'


def test_c38_binary_encodings_match_node_buffer():
    """types.ts:42-76 - Buffer base64/hex encode and Node's lenient decode."""
    assert Binary.to_base64(b'\x01\x02\x03\xfa') == 'AQID+g=='
    assert Binary.toBase64(b'') == ''
    assert bytes(Binary.from_base64('AQID+g==')) == b'\x01\x02\x03\xfa'
    assert bytes(Binary.fromBase64('AQID+g')) == b'\x01\x02\x03\xfa'
    assert bytes(Binary.fromBase64('AQ==ID')) == b'\x01'
    assert Binary.from_base64('') == b''
    assert Binary.to_hex(b'\x00\x0f\xff') == '000fff'
    assert Binary.toHex(b'\x00\x0f\xff') == '000fff'
    assert Binary.to_hex(b'') == ''
    assert bytes(Binary.from_hex('00ff10')) == b'\x00\xff\x10'
    assert bytes(Binary.fromHex('AB')) == b'\xab'
    assert Binary.from_hex('') == b''


def test_c39_binary_module_aliases_are_the_same_callables():
    """types.ts:78-85 - base64/hex ArrayBuffer aliases."""
    assert base64ToArrayBuffer is Binary.from_base64
    assert arrayBufferToBase64 is Binary.to_base64
    assert hexToArrayBuffer is Binary.from_hex
    assert arrayBufferToHex is Binary.to_hex
    assert bytes(base64ToArrayBuffer('AQID')) == b'\x01\x02\x03'
    assert arrayBufferToBase64(b'\x01\x02\x03') == 'AQID'
    assert bytes(hexToArrayBuffer('0102')) == b'\x01\x02'
    assert arrayBufferToHex(b'\x01\x02') == '0102'


def test_c40_clone_copies_containers_and_preserves_cycles():
    """types.ts:87-116 - deep clone over own keys, preserving prototype and cycles."""
    source = {'a': 1, 'b': {'c': 2}}
    result = clone(source)
    assert result == source
    assert result is not source
    assert result['b'] is not source['b']
    values = [1, [2, 3]]
    result = clone(values)
    assert result == values
    assert result is not values
    assert result[1] is not values[1]
    cyclic = {'a': 1}
    cyclic['self'] = cyclic
    result = clone(cyclic)
    assert result['a'] == 1
    assert result['self'] is result
    # `ArrayBuffer.isView` -> the view's own byte range becomes a fresh
    # buffer, so a `memoryview` clone is bytes and never raises.
    view = memoryview(b'\x01\x02\x03\x04')[1:3]
    copied = clone(view)
    assert isinstance(copied, memoryview) is False
    assert bytes(copied) == b'\x02\x03'
    # The reference reaches a nested view through own keys and elements.
    assert bytes(clone({'a': view})['a']) == b'\x02\x03'
    assert bytes(clone([view])[0]) == b'\x02\x03'
    assert bytes(clone((1, view))[1]) == b'\x02\x03'

    class Holder:
        def __init__(self, value):
            self.view = value

    class Slotted:
        __slots__ = ('view',)

        def __init__(self, value):
            self.view = value

    # A view held by an object is cloned like any other own key; a plain
    # `copy.deepcopy` would raise on it.
    assert bytes(clone(Holder(view)).view) == b'\x02\x03'
    assert bytes(clone(Slotted(view)).view) == b'\x02\x03'
    # Cycles are preserved while the view inside them is still copied.
    cyclic_with_view = {'view': view}
    cyclic_with_view['self'] = cyclic_with_view
    copied = clone(cyclic_with_view)
    assert copied['self'] is copied
    assert bytes(copied['view']) == b'\x02\x03'
    # An ArrayBuffer-like `bytearray` is copied, not shared.
    buffer = bytearray(b'\x01\x02')
    assert clone(buffer) == buffer
    assert clone(buffer) is not buffer
    assert bytes(clone(b'\x01\x02')) == b'\x01\x02'
    # A Date and an ArrayBuffer are rebuilt by the reference's leaf branches
    # (`new Date(source.valueOf())`, `source.slice(0)`), never shared.
    frozen = datetime.datetime(2026, 9, 3)
    assert clone(frozen) == frozen
    assert clone(frozen) is not frozen
    array_buffer = bytes(bytearray(b'\x01\x02'))
    assert clone(array_buffer) == array_buffer
    assert clone(array_buffer) is not array_buffer
    # Primitives pass through: `typeof source !== 'object'` returns the source.
    assert clone(5) == 5
    assert clone('a') == 'a'
    assert clone(None) is None


def test_c41_deep_equal_primitives_and_nullish():
    """types.ts:118-142 - `a === b` then the `!strict && isNullable` shortcut."""
    assert deepEqual(1, 1) is True
    assert deepEqual(1, 2) is False
    assert deepEqual(1, 1.0) is True
    assert deepEqual(1, True) is False
    assert deepEqual(0, False) is False
    assert deep_equal(None, None) is True
    # NaN === NaN is false, so a NaN pair is never equal.
    assert deep_equal(float('nan'), float('nan')) is False
    assert deepEqual('a', 'a') is True
    assert deepEqual('a', 'b') is False
    # Two equal strings are distinct Python objects; === still reports equal.
    left = json.loads('"' + 'x' * 40 + '"')
    right = json.loads('"' + 'x' * 40 + '"')
    assert left is not right
    assert deepEqual(left, right) is True
    assert deepEqual('1', 1) is False


def test_c42_deep_equal_structures():
    """types.ts:120-142 - Array/Date/RegExp/ArrayBuffer branches then own keys."""
    assert deepEqual([1, 2], [1, 2]) is True
    assert deepEqual([1, 2], [1, 3]) is False
    assert deepEqual([1, 2], [1, 2, 3]) is False
    assert deepEqual([], []) is True
    assert deepEqual([], {}) is False
    assert deepEqual(datetime.datetime(2026, 9, 3, 12), datetime.datetime(2026, 9, 3, 12)) is True
    assert deepEqual(datetime.datetime(2026, 9, 3, 12), datetime.datetime(2026, 9, 3, 13)) is False
    assert deep_equal(re.compile('a', re.I), re.compile('a', re.I)) is True
    assert deep_equal(re.compile('a', re.I), re.compile('a')) is False
    assert deep_equal(re.compile('a', re.I), re.compile('b', re.I)) is False
    assert deepEqual(b'\x01\x02', b'\x01\x02') is True
    assert deepEqual(b'\x01\x02', b'\x01') is False
    assert deepEqual(bytearray(b'\x01\x02'), b'\x01\x02') is True
    # `check(isArrayBufferLike, ...)`: an ArrayBuffer is never equal to a
    # view over the same bytes, which compares through its index keys.
    assert deepEqual(b'\x02\x03', memoryview(b'\x02\x03')) is False
    assert deep_equal(memoryview(b'\x02\x03'), b'\x02\x03') is False
    assert deepEqual(memoryview(b'\x02\x03'), memoryview(b'\x02\x03')) is True
    assert deepEqual(memoryview(b'\x02\x03'), memoryview(b'\x09\x09')) is False
    assert deepEqual(memoryview(b'\x02\x03'), [2, 3]) is False
    assert deep_equal(memoryview(b'\x02\x03'), {'0': 2, '1': 3}) is True
    assert deepEqual({'a': 1}, {'a': 1}) is True
    assert deepEqual({'a': 1}, {'a': 2}) is False
    assert deepEqual({'a': 1}, {'a': 1, 'b': 2}) is False
    assert deepEqual({'a': [1, {'b': 2}]}, {'a': [1, {'b': 2}]}) is True
    # Own enumerable keys of both operands take part in the comparison.
    assert deepEqual({'k': json.loads('"' + 'y' * 40 + '"')},
                     {'k': json.loads('"' + 'y' * 40 + '"')}) is True
    # A mapping subclass is still an object comparison.
    assert deep_equal({'a': 1}, collections.OrderedDict([('a', 1)])) is True


def test_c43_deep_equal_strict_disables_the_nullish_shortcut():
    """types.ts:120 - `if (!strict && isNullable(a) && isNullable(b)) return true`."""
    # Non-strict: a null field equals an absent one.
    assert deepEqual({'a': None}, {}) is True
    # Strict: the absent key reads as undefined, which is not null.
    assert deepEqual({'a': None}, {}, True) is False
    assert deepEqual({'a': 1}, {'a': 1}, True) is True


def test_c47_clone_leaf_branches_build_a_fresh_instance_per_occurrence():
    """types.ts:89-94 - Date/RegExp/ArrayBuffer/View return before `refs`."""
    date = datetime.datetime(2026, 9, 3, 12)
    assert clone(date) == date
    assert clone(date) is not date
    pattern = re.compile('a', re.I)
    copied = clone(pattern)
    assert copied is not pattern
    assert (copied.pattern, copied.flags) == (pattern.pattern, pattern.flags)
    assert copied.findall('xAx') == pattern.findall('xAx') == ['A']
    buffer = bytes(bytearray(b'\x01\x02'))
    assert clone(buffer) == buffer
    assert clone(buffer) is not buffer
    writable = bytearray(b'\x01\x02')
    assert clone(writable) == writable
    assert clone(writable) is not writable
    view = memoryview(b'\x01\x02\x03\x04')[1:3]
    assert bytes(clone(view)) == b'\x02\x03'
    assert clone(view) is not view
    # Each leaf branch returns before the `refs` lookup, so two occurrences of
    # one leaf become two independent copies...
    aliased = clone({'a': buffer, 'b': buffer})
    assert aliased['a'] == aliased['b']
    assert aliased['a'] is not aliased['b']
    # ...while a repeated container stays shared through the `refs` memo.
    shared = {'x': 1}
    holder = clone({'a': shared, 'b': shared})
    assert holder['a'] is holder['b']
    # Leaves are reached through own keys, elements, slots and cycles.
    nested = clone({'d': date, 'p': pattern, 'b': buffer, 'v': view})
    assert nested['d'] == date and nested['d'] is not date
    assert nested['p'] is not pattern
    assert nested['b'] is not buffer
    assert bytes(nested['v']) == b'\x02\x03'
    assert clone([buffer])[0] is not buffer
    assert clone((1, buffer))[1] is not buffer

    class Holder:
        def __init__(self):
            self.v = view
            self.d = date

    class Slotted:
        __slots__ = ('v', 'd')

        def __init__(self):
            self.v = view
            self.d = date

    assert bytes(clone(Holder()).v) == b'\x02\x03'
    assert clone(Holder()).d is not date
    assert bytes(clone(Slotted()).v) == b'\x02\x03'
    assert clone(Slotted()).d is not date
    cyclic = {'b': buffer}
    cyclic['self'] = cyclic
    copied_cyclic = clone(cyclic)
    assert copied_cyclic['self'] is copied_cyclic
    assert copied_cyclic['b'] is not buffer


def test_c48_deep_equal_reads_an_absent_own_key_as_undefined():
    """types.ts:141-142 - `deepEqual(a[key], b[key], strict)` over both key sets."""
    # Strict: a key only one operand has reads as `undefined`, which never
    # equals `null`, so the key names matter even when the counts match.
    assert deepEqual({'a': None}, {'b': None}, True) is False
    assert deepEqual({'a': None}, {'b': None}) is True
    assert deepEqual({'a': 1, 'b': None}, {'a': 1, 'c': None}, True) is False
    assert deepEqual({'a': 1, 'b': None}, {'a': 1, 'c': None}) is True
    assert deepEqual({'a': None}, {}, True) is False
    assert deepEqual({'a': None}, {}) is True
    assert deepEqual({'a': None}, {'a': None}, True) is True
    assert deepEqual({}, {}, True) is True
    # `strict` reaches the own-key recursion but not array elements: the array
    # branch is `deepEqual(item, b[index])` with no third argument, so elements
    # compare non-strict even inside a strict comparison.
    assert deepEqual({'x': {'a': None}}, {'x': {}}, True) is False
    assert deepEqual([{'a': None}], [{}], True) is True
    assert deepEqual([[{'a': None}]], [[{}]], True) is True
    assert deepEqual([{'x': {'a': None}}], [{'x': {}}], True) is True
    assert deepEqual({'k': [{'a': None}]}, {'k': [{}]}, True) is True
    assert deepEqual([1, [2]], [1, [2]], True) is True
    # Array length and the Array-vs-object branch are unchanged.
    assert deepEqual([1, 2], [1, 2, 3], True) is False
    assert deepEqual([1], {0: 1}, True) is False


def test_c44_reference_export_surface_is_present():
    """package.json/index.ts - every runtime export of the reference package."""
    import dsh.cordis.utils as module

    expected = [
        'contain', 'intersection', 'difference', 'union', 'deduplicate', 'remove', 'makeArray',
        'noop', 'isNullable', 'isNonNullable', 'isPlainObject', 'filterKeys', 'mapValues',
        'valueMap', 'pick', 'omit', 'defineProperty',
        'capitalize', 'uncapitalize', 'camelCase', 'camelize', 'paramCase', 'hyphenate',
        'snakeCase', 'formatProperty', 'trimSlash', 'sanitize',
        'Time', 'is', 'Binary', 'base64ToArrayBuffer', 'arrayBufferToBase64', 'hexToArrayBuffer',
        'arrayBufferToHex', 'clone', 'deepEqual',
    ]
    missing = []
    for name in expected:
        if name == 'is':
            # `is` is a Python keyword: the port exposes it as `is_`.
            resolved = module.is_
        else:
            resolved = getattr(module, name, None)
        if resolved is None:
            missing.append(name)
    assert missing == []
    assert getattr(Binary, 'is') is Binary.is_


# ---------------------------------------------------------------------------
# reference/vendor/cordis/src/utils.ts cases owned by the same module
# ---------------------------------------------------------------------------


def test_t1_disposable_list_identity_and_order():
    """cordis/utils.ts:5-31 - DisposableList keeps insertion order and O(1) delete."""
    values = DisposableList()
    first = object()
    second = object()
    remove_first = values.push(first)
    values.push(second)
    assert len(values) == 2
    assert list(values) == [first, second]
    assert values.delete(first) is True
    assert list(values) == [second]
    assert values.delete(object()) is False
    remove_first()
    assert len(values) == 1
    assert values.clear() == [second]
    assert list(values) == []

    # A bound method re-created by attribute access must still delete its entry.
    class Host:
        def disposer(self):
            return None

    host = Host()
    values.push(host.disposer)
    assert values.delete(host.disposer) is True
    assert len(values) == 0


def test_t2_get_traceable_returns_untracked_values():
    """cordis/utils.ts:117-125 - a value without `symbols.tracker` passes through."""
    class DummyContext:
        pass

    def plain():
        return 42

    context = DummyContext()
    assert get_traceable(context, plain) is plain
    assert get_traceable(context, 5) == 5


def test_t3_with_props_overlays_writable_properties():
    """cordis/utils.ts:128-140 - the overlay reads and writes through to props."""
    class Target:
        def __init__(self):
            self.foo = 'target_foo'
            self.bar = 'target_bar'

    target = Target()
    assert with_props(target, None) is target
    overlay = with_props(target, {'foo': 'overlay_foo'})
    assert overlay.foo == 'overlay_foo'
    assert overlay.bar == 'target_bar'
    overlay.foo = 'written'
    assert overlay.foo == 'written'
    assert target.foo == 'target_foo'


def test_t4_is_object_rejects_primitives_only():
    """cordis/utils.ts:102-104 - `value && (typeof value === 'object' || 'function')`."""
    class SlotClass:
        __slots__ = ('a', 'b')

        def __init__(self):
            self.a = 1
            self.b = 2

    assert is_object(SlotClass()) is True
    assert is_object({}) is True
    assert is_object(lambda: 1) is True
    assert is_object(None) is False
    assert is_object(123) is False
    assert is_object('string') is False
    assert is_object(True) is False


def test_t5_build_outer_stack_offset_slices_the_same_frames():
    """cordis/utils.ts:284-287 - `outerError.stack.split('\\n').slice(3 + offset)`."""
    frames_0 = build_outer_stack(0)()
    frames_1 = build_outer_stack(1)()
    assert isinstance(frames_0, list)
    assert isinstance(frames_1, list)
    assert frames_0[:-1] == frames_1


def test_t6_compose_error_attaches_the_outer_stack():
    """cordis/utils.ts:268-282 - composeError splices outer frames into the error."""
    seen = []

    def action(info):
        seen.append(info)
        raise ValueError('test error')

    get_outer = build_outer_stack(1)
    with pytest.raises(ValueError, match='test error') as excinfo:
        compose_error(action, get_outer_stack=get_outer)
    assert len(seen) == 1
    assert seen[0]['offset'] == 1
    assert excinfo.value._outer_stack == get_outer()


def test_t7_plugin_metadata_and_apply_signature():
    """cordis/registry.ts:100-111 - Plugin base class metadata attributes."""
    plugin = Plugin()
    assert hasattr(plugin, 'provide')
    assert hasattr(plugin, 'intercept')
    assert hasattr(plugin, 'Config')

    class SamplePlugin(Plugin):
        def apply(self, ctx, config=None):
            return 'applied'

    assert SamplePlugin().apply(None, {'key': 'val'}) == 'applied'
