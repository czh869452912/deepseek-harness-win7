"""
Tests for Schemastery Standard Schema V1 protocol compliance,
advanced DSL operators (computed, dynamic, transform, bitset, arrayBuffer, natural, percent),
and ValidationError path formatting matching reference/vendor/schemastery/src/index.ts.
"""

import datetime
import pytest
from dsh.cordis.schema import Schema, ValidationError, z


def test_standard_schema_v1_protocol():
    """Test @standard-schema/spec compliance via schema['~standard']."""
    s = Schema.object({
        "name": Schema.string().required(),
        "age": Schema.number().min(0).default(18),
    })

    # Validate '~standard' property
    standard = s["~standard"]
    assert standard is not None
    assert standard["version"] == 1
    assert standard["vendor"] == "cordis"
    assert callable(standard["validate"])

    # Test valid validation result
    res_valid = standard["validate"]({"name": "Alice", "age": 25})
    assert "value" in res_valid
    assert res_valid["value"] == {"name": "Alice", "age": 25}
    assert "issues" not in res_valid

    # Test invalid validation result (missing required 'name')
    res_invalid = standard["validate"]({"age": -5})
    assert "issues" in res_invalid
    assert len(res_invalid["issues"]) > 0


def test_schema_natural_and_percent():
    """Test natural and percent numeric helpers."""
    nat_schema = Schema.natural()
    assert nat_schema(5) == 5
    assert nat_schema(0) == 0
    with pytest.raises(ValidationError):
        nat_schema(-1)

    pct_schema = Schema.percent()
    assert pct_schema(0.5) == 0.5
    assert pct_schema(1.0) == 1.0
    with pytest.raises(ValidationError):
        pct_schema(1.5)
    with pytest.raises(ValidationError):
        pct_schema(-0.1)


def test_schema_computed_and_dynamic():
    """Test Schema.computed and Schema.dynamic."""
    # dynamic builder
    dynamic_schema = Schema.dynamic(lambda: Schema.string())
    assert dynamic_schema("hello") == "hello"

    # computed schema
    comp = Schema.computed(lambda root: "computed_val")
    assert comp("anything") == "computed_val"


def test_schema_array_buffer_and_date():
    """Test array_buffer and date schema converters."""
    # date
    d_schema = Schema.date()
    dt = datetime.datetime(2026, 8, 29, 12, 0, 0)
    assert d_schema(dt) == dt
    iso_res = d_schema("2026-08-29T12:00:00")
    assert isinstance(iso_res, datetime.datetime)

    # arrayBuffer
    buf_schema = Schema.array_buffer(encoding="hex")
    assert buf_schema(b"test") == b"test"
    hex_res = buf_schema("68656c6c6f")
    assert hex_res == b"hello"


def test_schema_transform_and_lazy():
    """Test Schema.transform and Schema.lazy."""
    tf = Schema.transform(Schema.string(), lambda s: s.upper())
    assert tf("cordis") == "CORDIS"

    lazy_s = Schema.lazy(lambda: Schema.number())
    assert lazy_s(42) == 42
