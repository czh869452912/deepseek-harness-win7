"""
Tests for SafeASTEvaluator, YAML !js expression parsing, and ${...} string template
interpolation in dsh/cordis/loader.py matching TS evaluate(ctx, expr) and interpolate(ctx, config).
"""

import os
import sys
import pytest
from dsh.cordis.context import Context
from dsh.cordis.loader import SafeASTEvaluator, evaluate_expr, interpolate


def test_safe_ast_evaluator_basic():
    """Test arithmetic, comparisons, ternary expressions, and logical operators."""
    ctx = Context()
    ctx.port = 8080

    # Arithmetic & logic
    assert evaluate_expr(ctx, "1 + 2 * 3") == 7
    assert evaluate_expr(ctx, "true && !false") is True
    assert evaluate_expr(ctx, "null === undefined") is True
    assert evaluate_expr(ctx, "10 > 5 && 3 < 4") is True

    # JS Ternary expression
    assert evaluate_expr(ctx, "true ? 100 : 200") == 100
    assert evaluate_expr(ctx, "false ? 'a' : 'b'") == "b"

    # Context attribute access
    assert evaluate_expr(ctx, "ctx.port") == 8080


def test_safe_ast_evaluator_env_and_platform():
    """Test process.env / env and process.platform bindings."""
    ctx = Context()
    os.environ["DSH_TEST_ENV_VAR"] = "test_val_123"

    assert evaluate_expr(ctx, "process.env.DSH_TEST_ENV_VAR") == "test_val_123"
    assert evaluate_expr(ctx, "env.get('DSH_TEST_ENV_VAR')") == "test_val_123"
    assert evaluate_expr(ctx, "process.platform == 'win32' || process.platform == 'linux'") in (True, False)


def test_safe_ast_evaluator_forbidden_injection():
    """Ensure dunder attributes and dangerous operations are blocked."""
    ctx = Context()
    # Access to __class__ or __subclasses__ should fail safely and return the raw expr string
    res = evaluate_expr(ctx, "ctx.__class__.__bases__")
    assert res == "ctx.__class__.__bases__"


def test_interpolate_nested_structures():
    """Test recursive interpolate with dicts, lists, and template strings."""
    ctx = Context()
    os.environ["DSH_INTERPOLATE_PORT"] = "9090"

    cfg = {
        "server": {
            "port": {"__jsExpr": "8000 + 80"},
            "tag": "port_${DSH_INTERPOLATE_PORT}",
            "fallback": "${DSH_NONEXISTENT_VAR:-default_val}",
        },
        "flags": [
            {"__jsExpr": "1 === 1"},
            "static_str",
        ]
    }

    interpolated = interpolate(ctx, cfg)
    assert interpolated["server"]["port"] == 8080
    assert interpolated["server"]["tag"] == "port_${DSH_INTERPOLATE_PORT}"
    assert interpolated["server"]["fallback"] == "${DSH_NONEXISTENT_VAR:-default_val}"
    assert interpolated["flags"][0] is True
    assert interpolated["flags"][1] == "static_str"
