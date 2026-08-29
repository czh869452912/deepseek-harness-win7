"""
1:1 Test Parity for Cosmokit utilities (string, time, misc)
Matching reference/vendor/cosmokit/src/*
"""

from dsh.cordis.utils import (
    capitalize,
    uncapitalize,
    camel_case,
    camelCase,
    hyphenate,
    paramCase,
    snake_case,
    snakeCase,
    is_nullable,
    isNullable,
    Time,
)


def test_cosmokit_string_casing():
    """Verify string casing helpers."""
    assert capitalize("foo") == "Foo"
    assert uncapitalize("Foo") == "foo"
    assert camel_case("foo-bar") == "fooBar"
    assert camelCase("foo_bar") == "fooBar"
    assert hyphenate("fooBar") == "foo-bar"
    assert paramCase("foo_bar_baz") == "foo-bar-baz"
    assert snake_case("fooBar") == "foo_bar"
    assert snakeCase("foo-bar-baz") == "foo_bar_baz"


def test_cosmokit_time_parsing_and_formatting():
    """Verify Time constants, parse_time, and format."""
    assert Time.second == 1000
    assert Time.minute == 60000
    assert Time.hour == 3600000
    assert Time.day == 86400000

    # Parsing
    assert Time.parse_time("10s") == 10000
    assert Time.parse_time("5m") == 300000
    assert Time.parse_time("1h") == 3600000
    assert Time.parse_time("1d") == 86400000

    # Formatting
    assert Time.format(500) == "500ms"
    assert Time.format(10000) == "10s"
    assert Time.format(120000) == "2m"
    assert Time.format(7200000) == "2h"
    assert Time.format(172800000) == "2d"


def test_cosmokit_nullability():
    """Verify is_nullable and isNullable."""
    assert is_nullable(None) is True
    assert isNullable(None) is True
    assert is_nullable("") is False
    assert is_nullable(0) is False
    assert is_nullable(False) is False
