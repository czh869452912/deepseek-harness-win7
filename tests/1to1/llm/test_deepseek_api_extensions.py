"""
1:1 parity suite for `@deepseek-ai/dsh-deepseek-llm-api-extensions`
(`dsh/llm/deepseek_api_extensions.py`).

Upstream is
reference/packages/llm/deepseek-llm-api-extensions/tests/registry.spec.ts.
Every case keeps the upstream setup, action, and assertions: detached frozen
field values, the joint acceptance transaction settling each provider exactly
once, receiver preservation, duplicate rejection with fiber-scoped release,
all-settled failure reporting, and cancellation that stops waiting for a
provider ignoring the request signal.

The platform `AggregateError` is `ExtensionAcceptanceError` in Python 3.8
(`ExceptionGroup` is 3.11+); the case asserts the same `errors` sequence and
message.
"""

import asyncio
from typing import Any, Dict, List

import pytest

from dsh.core.abort import AbortController, AbortSignal
from dsh.core.session.json import FrozenDict
from dsh.cordis.context import Context
from dsh.llm.deepseek_api_extensions import (
    AGGREGATE_MESSAGE,
    DeepSeekLlmApiExtensionRegistry,
    ExtensionAcceptanceError,
)

SIGNAL = AbortSignal()


def request(**overrides: Any) -> Dict[str, Any]:
    """One exact serialized request's extension-facing facts."""
    value: Dict[str, Any] = {"body": {}, "signal": SIGNAL}
    value.update(overrides)
    return value


async def harness() -> Context:
    ctx = Context()
    await ctx.plugin(DeepSeekLlmApiExtensionRegistry)
    return ctx


def release(disposer: Any) -> Any:
    """Run an effect disposer, awaiting the cleanup when it is asynchronous."""
    result = disposer() if callable(disposer) else disposer
    return result


@pytest.mark.asyncio
async def test_prepares_detached_fields_and_accepts_every_provider_exactly_once():
    ctx = await harness()
    first: List[str] = []
    second: List[str] = []
    mutable = {"value": "original"}
    ctx.deepseekLlmApiExtensions.register(
        "test_alpha", {"prepare": lambda _request: {"value": mutable, "accept": lambda: first.append("a")}}
    )

    async def prepare_beta(incoming: Dict[str, Any]) -> Dict[str, Any]:
        async def accept() -> None:
            second.append("b")

        return {"value": [0 if incoming["body"].get("messages") is None else 1], "accept": accept}

    ctx.deepseekLlmApiExtensions.register("test_beta", {"prepare": prepare_beta})

    prepared = await ctx.deepseekLlmApiExtensions.prepare(
        request(body={"messages": []}, sessionId="s")
    )
    mutable["value"] = "changed"
    assert dict(prepared.fields) == {"test_alpha": {"value": "original"}, "test_beta": [1]}
    assert isinstance(prepared.fields, FrozenDict)
    assert isinstance(prepared.fields["test_alpha"], FrozenDict)

    await asyncio.gather(prepared.accept(), prepared.accept())
    await prepared.accept()
    assert first == ["a"]
    assert second == ["b"]


@pytest.mark.asyncio
async def test_preserves_the_prepared_result_as_an_acceptance_method_receiver():
    ctx = await harness()

    class Result:
        def __init__(self) -> None:
            self.value = {"value": "receiver"}
            self.accepted = 0

        def accept(self) -> None:
            self.accepted += 1

    result = Result()
    ctx.deepseekLlmApiExtensions.register("test_alpha", {"prepare": lambda _request: result})

    prepared = await ctx.deepseekLlmApiExtensions.prepare(request())
    await prepared.accept()
    assert result.accepted == 1


@pytest.mark.asyncio
async def test_rejects_duplicate_fields_and_releases_ownership_with_the_registering_fiber():
    ctx = await harness()
    owner = ctx.extend()
    dispose = owner.deepseekLlmApiExtensions.register(
        "test_alpha", {"prepare": lambda _request: {"value": {"value": "one"}}}
    )
    with pytest.raises(ValueError, match="already registered"):
        ctx.deepseekLlmApiExtensions.register(
            "test_alpha", {"prepare": lambda _request: {"value": {"value": "two"}}}
        )

    release(dispose)
    ctx.deepseekLlmApiExtensions.register(
        "test_alpha", {"prepare": lambda _request: {"value": {"value": "replacement"}}}
    )
    prepared = await ctx.deepseekLlmApiExtensions.prepare(request())
    assert dict(prepared.fields) == {"test_alpha": {"value": "replacement"}}


@pytest.mark.asyncio
async def test_settles_every_acceptance_callback_before_reporting_one_or_several_failures():
    ctx = await harness()
    later: List[str] = []

    def alpha_accept() -> None:
        raise RuntimeError("alpha failed")

    def beta_accept() -> None:
        later.append("beta")
        raise RuntimeError("beta failed")

    ctx.deepseekLlmApiExtensions.register(
        "test_alpha", {"prepare": lambda _request: {"value": {"value": "x"}, "accept": alpha_accept}}
    )
    ctx.deepseekLlmApiExtensions.register(
        "test_beta", {"prepare": lambda _request: {"value": [2], "accept": beta_accept}}
    )

    prepared = await ctx.deepseekLlmApiExtensions.prepare(request())
    with pytest.raises(ExtensionAcceptanceError) as raised:
        await prepared.accept()
    assert raised.value.errors and [str(error) for error in raised.value.errors] == [
        "alpha failed",
        "beta failed",
    ]
    assert str(raised.value) == AGGREGATE_MESSAGE
    assert later == ["beta"]


@pytest.mark.asyncio
async def test_reports_a_single_acceptance_failure_verbatim_and_omits_an_undefined_contribution():
    ctx = await harness()
    failure = RuntimeError("single failure")
    ctx.deepseekLlmApiExtensions.register(
        "test_alpha",
        {
            "prepare": lambda _request: {
                "value": {"value": "x"},
                "accept": lambda: (_ for _ in ()).throw(failure),
            }
        },
    )
    ctx.deepseekLlmApiExtensions.register("test_beta", {"prepare": lambda _request: None})

    prepared = await ctx.deepseekLlmApiExtensions.prepare(request())
    assert dict(prepared.fields) == {"test_alpha": {"value": "x"}}
    with pytest.raises(RuntimeError) as raised:
        await prepared.accept()
    assert raised.value is failure


@pytest.mark.asyncio
async def test_rejects_invalid_field_names_and_preparation_failures_before_returning_fields():
    ctx = await harness()
    with pytest.raises(ValueError, match="non-blank trimmed"):
        ctx.deepseekLlmApiExtensions.register(
            "", {"prepare": lambda _request: {"value": {"value": "x"}}}
        )

    def failing_prepare(_request: Any) -> Any:
        raise RuntimeError("prepare failed")

    ctx.deepseekLlmApiExtensions.register("test_alpha", {"prepare": failing_prepare})
    with pytest.raises(RuntimeError, match="prepare failed"):
        await ctx.deepseekLlmApiExtensions.prepare(request())


@pytest.mark.asyncio
async def test_stops_waiting_for_a_provider_that_ignores_request_cancellation():
    ctx = await harness()
    controller = AbortController()
    started = asyncio.Event()

    async def never_settles() -> Any:
        await asyncio.Event().wait()

    def prepare_forever(_request: Any) -> Any:
        started.set()
        return never_settles()

    ctx.deepseekLlmApiExtensions.register("test_alpha", {"prepare": prepare_forever})

    pending = asyncio.ensure_future(
        ctx.deepseekLlmApiExtensions.prepare(request(signal=controller.signal))
    )
    await started.wait()
    reason = RuntimeError("cancelled during extension preparation")
    controller.abort(reason)

    with pytest.raises(RuntimeError) as raised:
        await asyncio.wait_for(pending, timeout=5.0)
    assert raised.value is reason
