"""
1:1 Unit tests for interpolate & JS expressions in Cordis Loader
Matching reference/vendor/loader/src/config/utils.ts
"""

import sys
import pytest
from dsh.cordis.context import Context
from dsh.cordis.loader import interpolate, is_js_expr, evaluate_expr, eval_condition


def test_is_js_expr():
    assert is_js_expr({"__jsExpr": "1 + 1"}) is True
    assert is_js_expr("!!js 1 + 1") is False
    assert is_js_expr({"a": 1}) is False


def test_evaluate_expr():
    ctx = Context()
    ctx.set_service("sample", {"port": 8080})

    assert evaluate_expr(ctx, "1 + 2") == 3
    assert evaluate_expr(ctx, "ctx.sample['port']") == 8080
    assert evaluate_expr(ctx, "sys.platform == 'win32'") == (sys.platform == "win32")
    assert evaluate_expr(ctx, "process.platform === 'win32'") == (sys.platform == "win32")


def test_interpolate_recursive():
    ctx = Context()
    ctx.set_service("config", {"api_base": "https://api.deepseek.com"})

    raw_config = {
        "server": {
            "url": {"__jsExpr": "ctx.config['api_base'] + '/v1'"},
            "timeout": 30,
        },
        "features": [
            "auth",
            {"__jsExpr": "'dynamic_' + ('win' if sys.platform == 'win32' else 'posix')"}
        ]
    }

    resolved = interpolate(ctx, raw_config)
    assert resolved["server"]["url"] == "https://api.deepseek.com/v1"
    assert resolved["server"]["timeout"] == 30
    expected_platform_feat = "dynamic_win" if sys.platform == "win32" else "dynamic_posix"
    assert resolved["features"][1] == expected_platform_feat


def test_eval_condition():
    ctx = Context()
    assert eval_condition(True, ctx) is True
    assert eval_condition(False, ctx) is False
    assert eval_condition("!!js sys.platform == 'win32'", ctx) == (sys.platform == "win32")
    assert eval_condition({"__jsExpr": "1 < 2"}, ctx) is True
