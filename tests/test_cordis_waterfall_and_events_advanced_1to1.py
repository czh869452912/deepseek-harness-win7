"""
1:1 Advanced unit tests for EventBus, Waterfall pipelines, and listener interception in Cordis
Matching reference/vendor/cordis/src/events.ts
"""

import pytest
import asyncio
from dsh.cordis.context import Context


@pytest.mark.asyncio
async def test_waterfall_async_pipeline_and_short_circuit():
    ctx = Context()

    calls = []

    # Middleware 1: Appends "m1", calls next
    async def m1(data, next_fn=None):
        calls.append("m1_in")
        res = await next_fn(data + "_m1") if next_fn else data + "_m1"
        calls.append("m1_out")
        return res

    # Middleware 2: Short-circuits (does not call next_fn)
    async def m2(data, next_fn=None):
        calls.append("m2_short")
        return data + "_short"

    # Middleware 3: Should NOT be reached
    async def m3(data, next_fn=None):
        calls.append("m3")
        return await next_fn(data + "_m3") if next_fn else data + "_m3"

    ctx.on("test/pipeline", m1)
    ctx.on("test/pipeline", m2)
    ctx.on("test/pipeline", m3)

    result = await ctx.waterfall("test/pipeline", "init")
    assert result == "init_m1_short"
    assert calls == ["m1_in", "m2_short", "m1_out"]


def test_waterfall_sync_pipeline():
    ctx = Context()

    def step1(num, next_fn=None):
        return next_fn(num * 2) if next_fn else num * 2

    def step2(num, next_fn=None):
        return next_fn(num + 10) if next_fn else num + 10

    ctx.on("math/calc", step1)
    ctx.on("math/calc", step2)

    res = ctx.waterfall_sync("math/calc", 5)
    assert res == 20  # (5 * 2) + 10


def test_bail_sync_short_circuit():
    ctx = Context()

    ctx.on("check/auth", lambda user: None)  # Returns falsy -> continue
    ctx.on("check/auth", lambda user: "DENIED" if user == "guest" else None)
    ctx.on("check/auth", lambda user: "ALLOWED")

    assert ctx.bail_sync("check/auth", "guest") == "DENIED"
    assert ctx.bail_sync("check/auth", "admin") == "ALLOWED"
