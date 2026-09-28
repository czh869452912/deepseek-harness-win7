import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.session import SessionPlugin
from dsh.llm.llm_retry import LLMRetryPlugin
from dsh.llm.retry_policy import resolve_retry_policy


def policy(mode="normal", **kwargs):
    return resolve_retry_policy(dict(mode=mode, backoff={"initialDelayMs": 1, "maxDelayMs": 2, "jitterRatio": 0}, **kwargs))


@pytest.mark.parametrize("raw", [
    {"mode": "normal", "maxRetries": True}, {"mode": "normal", "retryableCodes": []},
    {"mode": "normal", "retryableCodes": ["SERVER", "SERVER"]},
    {"mode": "always", "extra": 1}, {"mode": "always", "backoff": {"initialDelayMs": 0}},
    {"mode": "always", "backoff": {"initialDelayMs": 10, "maxDelayMs": 1}},
])
def test_invalid_provider_policy_is_rejected(raw):
    with pytest.raises(ValueError):
        resolve_retry_policy(raw)


async def setup():
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(AgentPlugin)
    fiber = await ctx.plugin(LLMRetryPlugin)
    session = ctx.get("sessions").create("retry-policy")
    payload = dict(agent=SimpleNamespace(session=session), provider="provider-a", turn=1, step=1,
                   failure={"code": "SERVER", "message": "temporarily unavailable"},
                   signal=asyncio.Event(), retryPolicy=policy(maxRetries=1))
    return ctx, fiber, payload


async def recover(ctx, payload):
    return await ctx.waterfall("agent/request-error", payload, lambda *_: None)


@pytest.mark.asyncio
async def test_retry_count_survives_plugin_replacement_and_is_policy_and_provider_scoped():
    ctx, fiber, payload = await setup()
    try:
        assert await recover(ctx, payload) == {"kind": "retry"}
        events = payload["agent"].session.events
        assert [e["type"] for e in events][-2:] == ["llm/retry", "llm/retry-started"]
        await fiber.dispose()
        await ctx.plugin(LLMRetryPlugin)
        assert await recover(ctx, payload) is None
        payload["provider"] = "provider-b"
        assert await recover(ctx, payload) == {"kind": "retry"}
        payload["retryPolicy"] = policy(maxRetries=2)
        assert await recover(ctx, payload) == {"kind": "retry"}
        assert events[-2]["data"]["retry"] == 1
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_code_matching_is_exact_and_excess_retry_after_delegates():
    ctx, _, payload = await setup()
    try:
        payload["failure"] = {"code": "AUTH", "message": "SERVER 500 timeout"}
        assert await recover(ctx, payload) is None
        payload["failure"] = {"code": "SERVER", "message": "wait", "providerRetryAfterMs": 3}
        assert await recover(ctx, payload) is None
        assert not any(e["type"] == "llm/retry" for e in payload["agent"].session.events)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispose", [False, True])
async def test_cancel_and_dispose_stop_wait_without_retry_started(dispose):
    ctx, fiber, payload = await setup()
    payload["retryPolicy"] = resolve_retry_policy({"mode": "always", "backoff": {"initialDelayMs": 10000}})
    task = asyncio.create_task(recover(ctx, payload))
    try:
        for _ in range(100):
            if any(e["type"] == "llm/retry" for e in payload["agent"].session.events):
                break
            await asyncio.sleep(0)
        if dispose:
            await asyncio.wait_for(fiber.dispose(), 1)
        else:
            payload["signal"].set()
        assert await asyncio.wait_for(task, 1) is None
        types = [e["type"] for e in payload["agent"].session.events]
        assert "llm/retry" in types and "llm/retry-started" not in types
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_always_honors_downstream_retry_and_contains_downstream_failure():
    ctx, _, payload = await setup()
    payload["retryPolicy"] = policy("always", maxRetries="inactive", retryableCodes=[])
    async def fail(*_):
        raise ValueError("downstream failure")
    try:
        assert await ctx.waterfall("agent/request-error", payload, lambda *_: {"kind": "retry"}) == {"kind": "retry"}
        assert not any(e["type"] == "llm/retry" for e in payload["agent"].session.events)
        assert await ctx.waterfall("agent/request-error", payload, fail) == {"kind": "retry"}
    finally:
        await ctx.fiber.dispose()
