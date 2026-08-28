"""
1:1 Unit tests for Schemastery / Standard Schema V1 engine in Cordis
Matching reference/vendor/schemastery/src/index.ts
"""

import pytest
import datetime
import re
from dsh.cordis.schema import Schema, ValidationError, z


def test_schema_primitive_types_validation():
    # String
    str_schema = Schema.string().min(2).max(5).pattern(r"^[a-z]+$")
    assert str_schema("abc") == "abc"
    with pytest.raises(ValidationError):
        str_schema("a")  # too short
    with pytest.raises(ValidationError):
        str_schema("abcdef")  # too long
    with pytest.raises(ValidationError):
        str_schema("123")  # pattern mismatch

    # Number / Natural / Percent
    num_schema = Schema.number().min(0).max(100).step(5)
    assert num_schema(25) == 25
    with pytest.raises(ValidationError):
        num_schema(23)  # not multiple of 5

    nat_schema = Schema.natural()
    assert nat_schema(10) == 10
    with pytest.raises(ValidationError):
        nat_schema(-1)

    pct_schema = Schema.percent()
    assert pct_schema(0.75) == 0.75
    with pytest.raises(ValidationError):
        pct_schema(1.5)

    # Boolean
    bool_schema = Schema.boolean()
    assert bool_schema(True) is True
    assert bool_schema(False) is False
    with pytest.raises(ValidationError):
        bool_schema("true")


def test_schema_object_and_dict():
    # Object with defined schema
    user_schema = Schema.object({
        "name": Schema.string().required(),
        "age": Schema.number().default(18),
        "role": Schema.string().default("user"),
    })

    res = user_schema({"name": "Alice"})
    assert res == {"name": "Alice", "age": 18, "role": "user"}

    with pytest.raises(ValidationError):
        user_schema({"age": 20})  # missing required 'name'

    # Dict with dynamic keys
    scores_schema = Schema.dict(Schema.number(), Schema.string().pattern(r"^[A-Z]+$"))
    res_dict = scores_schema({"MATH": 95, "ENG": 88})
    assert res_dict == {"MATH": 95, "ENG": 88}

    with pytest.raises(ValidationError):
        scores_schema({"math_low": 90})  # invalid key pattern


def test_schema_array_and_tuple():
    tags_schema = Schema.array(Schema.string()).max(3)
    assert tags_schema(["a", "b"]) == ["a", "b"]
    with pytest.raises(ValidationError):
        tags_schema(["a", "b", "c", "d"])  # exceeds max

    pair_schema = Schema.tuple([Schema.string(), Schema.number()])
    assert pair_schema(["id", 42]) == ["id", 42]


def test_schema_union_and_intersect():
    # Union
    union_schema = Schema.union([Schema.string(), Schema.number()])
    assert union_schema("hello") == "hello"
    assert union_schema(123) == 123
    with pytest.raises(ValidationError):
        union_schema(True)

    # Intersect
    inter_schema = Schema.intersect([
        Schema.object({"a": Schema.string().default("A")}),
        Schema.object({"b": Schema.number().default(2)}),
    ])
    assert inter_schema({}) == {"a": "A", "b": 2}


def test_schema_transform_and_lazy():
    # Transform
    date_schema = Schema.date()
    now = datetime.datetime.now()
    iso_str = now.isoformat()
    assert isinstance(date_schema(iso_str), datetime.datetime)

    # Lazy recursive schema
    node_schema = Schema.lazy(lambda: Schema.object({
        "value": Schema.string(),
        "children": Schema.array(node_schema).default([]),
    }))

    tree_data = {"value": "root", "children": [{"value": "leaf"}]}
    assert node_schema(tree_data) == {"value": "root", "children": [{"value": "leaf", "children": []}]}


def test_schema_simplify():
    config_schema = Schema.object({
        "host": Schema.string().default("127.0.0.1"),
        "port": Schema.number().default(8080),
        "debug": Schema.boolean().default(False),
    })

    # Strips default values for persistence
    full_data = {"host": "127.0.0.1", "port": 9000, "debug": False}
    simplified = config_schema.simplify(full_data)
    assert simplified == {"port": 9000}


def test_standard_schema_validate_interface():
    s = z.object({
        "apiKey": z.string().required(),
    })
    ok_res = s.validate({"apiKey": "sk-123"})
    assert "value" in ok_res
    assert ok_res["value"]["apiKey"] == "sk-123"

    fail_res = s.validate({})
    assert "issues" in fail_res
    assert len(fail_res["issues"]) > 0
