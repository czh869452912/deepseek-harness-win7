"""
Advanced 1:1 unit tests for Schemastery specification
Matching reference/vendor/schemastery/src/index.ts
Covers i18n, roles, links, deprecation, experimental badges, bitsets, regex, array buffer, and toJSON.
"""

import pytest
import re
from dsh.cordis.schema import Schema, ValidationError, z


def test_schema_i18n_multilingual_descriptions():
    s = Schema.object({
        "username": Schema.string().description("Default description"),
        "password": Schema.string().description("User password"),
    }).i18n({
        "zh-CN": {
            "$description": "用户配置表单",
            "username": "用户名",
            "password": "密码",
        },
        "en-US": {
            "$description": "User configuration form",
            "username": "Username",
            "password": "Password",
        }
    })

    json_out = s.to_json()
    assert "dict" in json_out
    user_desc = json_out["dict"]["username"]["meta"]["description"]
    assert user_desc["zh-CN"] == "用户名"
    assert user_desc["en-US"] == "Username"


def test_schema_roles_links_and_badges():
    s = Schema.string().role("secret", {"masked": True}).link("https://docs.deepseek.com").deprecated().experimental()

    json_out = s.to_json()
    assert json_out["meta"]["role"] == "secret"
    assert json_out["meta"]["extra"] == {"masked": True}
    assert json_out["meta"]["link"] == "https://docs.deepseek.com"
    badges = json_out["meta"]["badges"]
    assert any(b["text"] == "deprecated" for b in badges)
    assert any(b["text"] == "experimental" for b in badges)


def test_schema_bitset_resolution():
    bits = {
        "READ": 1,
        "WRITE": 2,
        "EXEC": 4,
    }
    bit_schema = Schema.bitset(bits)

    # Resolve from integer
    val, keys = Schema.resolve(3, bit_schema)
    assert val == 3
    assert "READ" in keys
    assert "WRITE" in keys
    assert "EXEC" not in keys

    # Resolve from array of strings
    val2, keys2 = Schema.resolve(["READ", "EXEC"], bit_schema)
    assert val2 == 5


def test_schema_regex_and_array_buffer():
    # RegExp
    reg_schema = Schema.reg_exp()
    pat = reg_schema(r"^[0-9]+$")
    assert isinstance(pat, re.Pattern)
    assert pat.match("12345") is not None

    # ArrayBuffer / Bytes
    buf_schema = Schema.array_buffer()
    assert buf_schema(b"hello") == b"hello"
    assert buf_schema(bytearray(b"world")) == bytearray(b"world")
    with pytest.raises(ValidationError):
        buf_schema("not-bytes")


def test_schema_loose_mode():
    s = Schema.number().default(42).loose()
    # When loose is True, invalid input falls back to default instead of raising
    assert s("not-a-number") == 42
