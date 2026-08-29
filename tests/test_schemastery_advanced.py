import pytest
from dsh.cordis.schema import Schema, ValidationError, z


def test_schema_intersect_varargs():
    s1 = Schema.object({"a": Schema.string()})
    s2 = Schema.object({"b": Schema.number()})
    s = Schema.intersect(s1, s2)

    res = s({"a": "hello", "b": 123})
    assert res["a"] == "hello"
    assert res["b"] == 123


def test_schema_tuple_varargs():
    s = Schema.tuple(Schema.string(), Schema.number())
    res = s(["first", 42])
    assert res == ["first", 42]

    with pytest.raises(ValidationError):
        s([123, "wrong"])


def test_schema_dynamic_factory():
    flag = True
    def make_schema():
        return Schema.string() if flag else Schema.number()

    s = Schema.dynamic(make_schema)
    assert s("abc") == "abc"

    flag = False
    assert s(123) == 123


def test_schema_transform():
    s = Schema.transform(Schema.string(), lambda v, opt: v.upper())
    assert s("hello") == "HELLO"
