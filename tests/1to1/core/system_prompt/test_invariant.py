"""
1:1 port of reference/packages/core/system-prompt/tests/invariant.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import re
from typing import Any, Dict
import pytest

from dsh.cordis.context import Context
from dsh.core.system_prompt import SystemPromptInvariantPlugin
from dsh.diagnostics.invariants import InvariantRegistry


async def setup_ctx() -> Context:
    ctx = Context()
    await ctx.plugin(InvariantRegistry)
    await ctx.plugin(SystemPromptInvariantPlugin)
    return ctx


def valid() -> Dict[str, Any]:
    return {
        "sections": [{"name": "identity", "text": "prompt"}],
        "contexts": [{"name": "policy", "text": "current policy"}],
        "tools": [{"name": "echo", "description": "Echo", "parameters": {}}],
        "variables": {"cwd": "/repo", "optional": None},
    }


async def assemble(ctx: Context, result: Dict[str, Any]) -> Dict[str, Any]:
    return await ctx.waterfall(
        "system-prompt/assemble",
        valid(),
        {},
        lambda: result,
    )


@pytest.mark.asyncio
async def test_accepts_well_formed_authoritative_assembly():
    ctx = await setup_ctx()
    res = await assemble(ctx, valid())
    assert res == valid()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "assembly,pattern",
    [
        (
            dict(valid(), sections=[{"name": "", "text": "x"}]),
            r"section names must be non-empty",
        ),
        (
            dict(valid(), sections=[{"name": "x", "text": "a"}, {"name": "x", "text": "b"}]),
            r'section name "x" is duplicated',
        ),
        (
            dict(valid(), sections=[{"name": "x", "text": 1}]),
            r'section "x" text must be a string',
        ),
        (
            dict(valid(), contexts=[{"name": "", "text": "x"}]),
            r"context names must be non-empty",
        ),
        (
            dict(valid(), contexts=[{"name": "x", "text": "a"}, {"name": "x", "text": "b"}]),
            r'context name "x" is duplicated',
        ),
        (
            dict(valid(), contexts=[{"name": "x", "text": 1}]),
            r'context "x" text must be a string',
        ),
        (
            dict(valid(), tools=[{"name": "", "description": "x", "parameters": {}}]),
            r"tool names must be non-empty",
        ),
        (
            dict(valid(), variables={"Bad": "x"}),
            r'variable name "Bad" is invalid',
        ),
        (
            dict(valid(), variables={"value": 1}),
            r'variable "value" must be a string or undefined',
        ),
    ],
)
async def test_rejects_malformed_authoritative_assembly(assembly, pattern):
    ctx = await setup_ctx()
    with pytest.raises(Exception, match=pattern):
        await assemble(ctx, assembly)
