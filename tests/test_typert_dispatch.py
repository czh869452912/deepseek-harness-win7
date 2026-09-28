import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.typert.registry import TypertRegistry
from dsh.typert.remote import Remote, RemoteScope, TypertRemoteService, TypertLookupFailure
from dsh.typert.protocol import TypertLookupProvider
from dsh.typert.dispatch import RemoteDispatcher, TypertGatewayError, RemoteInvocationCancelled, rpc_failure
from dsh.typert.artifact import Schema, UNDEFINED, read_generated_artifact


class Example(TypertRemoteService):
    def __init__(self, ctx):
        super().__init__(ctx, "example")
        self.entered, self.closed = asyncio.Event(), asyncio.Event()

    @Remote
    def read(self, session, data):
        return {"session": session, "data": data}

    @Remote("renamed")
    def named(self, value):
        return value

    @Remote
    def invalid(self, value=1):
        return value

    @Remote({"mode": "stream"})
    async def watch(self, signal):
        try:
            self.entered.set()
            await asyncio.Event().wait()
            yield "unused"
        finally:
            self.closed.set()

    @RemoteScope("agent")
    def scoped(self, value):
        return [self.ctx.get("tag"), value]


def request(method, args=None, signal=None):
    return {"namespace": "example", "method": method, "args": args or {}, "signal": signal}


async def setup():
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    await ctx.plugin(Example)
    ctx.get("typert").lookups.register("session", TypertLookupProvider("session", "sessionId", "host#Session", "wire#SessionId", lambda key: "resolved:" + key))
    return ctx, RemoteDispatcher(ctx)


@pytest.mark.asyncio
async def test_src_markers_rename_lookup_and_absent_arguments():
    ctx, gateway = await setup()
    try:
        assert gateway.claims_endpoint("example/read")
        assert not gateway.claims_endpoint("example/named")
        assert await gateway.invoke(request("renamed", {"value": "yes"})) == "yes"
        result = await gateway.invoke(request("read", {"sessionId": "s1"}))
        assert result["session"] == "resolved:s1" and result["data"] is UNDEFINED
        with pytest.raises(TypertGatewayError) as caught:
            await gateway.invoke(request("invalid"))
        assert caught.value.code == "signature-invalid"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_strict_codec_exact_fields_and_withdrawal_forbids_src_fallback():
    ctx, gateway = await setup()
    row = {"id": "fixture#read", "service": "example", "namespace": "example", "method": "read", "invocation": {"kind": "direct"},
           "parameters": [{"name": "session", "wire": "sessionId", "source": "lookup", "lookup": "session", "codec": {"mode": "strict", "typeSymbol": "wire#SessionId", "schema": Schema("string")}},
                          {"name": "data", "wire": "data", "source": "json", "codec": {"mode": "strict", "typeSymbol": "Data", "schema": Schema("object", [{"text": Schema("string")}])}}],
           "result": {"mode": "src-json"}}
    dispose = ctx.get("typert").register({"package": "fixture", "face": "host", "schemas": [], "model": {}, "invocations": [row]})
    try:
        result = await gateway.invoke(request("read", {"sessionId": "s", "data": {"text": "yes", "unused": 1}}))
        assert result == {"session": "resolved:s", "data": {"text": "yes"}}
        for args, code in [({"sessionId": "s"}, "arguments-invalid"), ({"sessionId": "s", "data": {"text": 2}}, "input-invalid"), ({"sessionId": "s", "data": {"text": "yes"}, "extra": None}, "arguments-invalid")]:
            with pytest.raises(TypertGatewayError) as caught:
                await gateway.invoke(request("read", args))
            assert caught.value.code == code
        dispose()
        with pytest.raises(TypertGatewayError) as caught:
            await gateway.invoke(request("read", {"sessionId": "s"}))
        assert caught.value.code == "definition-unavailable"
        assert gateway.claims_endpoint("example/read")
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_context_receiver_uses_selected_context_and_policy_error_identity():
    ctx, gateway = await setup()
    child = ctx.extend()
    child.set_service("tag", "selected")
    registry = ctx.get("typert")
    registry.contexts.registerHost("agent", SimpleNamespace(wire="agentId", wireTypeSymbol="AgentId", identity=lambda _: None, resolve=lambda _: child))
    try:
        assert await gateway.invoke(request("scoped", {"agentId": "a", "value": 5})) == ["selected", 5]
        failure = TypertLookupFailure({"code": "denied", "message": "No access", "details": {}})
        def reject(_):
            raise failure
        registry.lookups.configure("session", reject)
        with pytest.raises(TypertLookupFailure) as caught:
            await gateway.invoke(request("read", {"sessionId": "secret"}))
        assert caught.value is failure
        assert rpc_failure(failure)["error"] is failure.failure
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_stream_abort_closes_iterator_and_unary_stream_modes_do_not_mix():
    ctx, gateway = await setup()
    controller = AbortController()
    try:
        with pytest.raises(TypertGatewayError) as caught:
            await gateway.invoke(request("watch", signal=controller.signal))
        assert caught.value.code == "signature-invalid"
        stream = await gateway.stream(request("watch", signal=controller.signal))
        pending = asyncio.create_task(stream.__anext__())
        await ctx.get("example").entered.wait()
        controller.abort()
        with pytest.raises(RemoteInvocationCancelled):
            await asyncio.wait_for(pending, 1)
        assert ctx.get("example").closed.is_set()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_llm_generated_contract_dispatch_and_discovery_error():
    from dsh.llm.llm_service import LlmRuntime
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    await ctx.plugin(LlmRuntime)
    ctx.get("typert").register(read_generated_artifact("packages/llm/llm/lib/typert.host.js"))
    gateway = RemoteDispatcher(ctx)
    signal = AbortController().signal
    captured = []
    async def discover(options, caller_signal):
        captured.append((options, caller_signal))
        return [{"id": "a"}, {"id": "a"}]
    ctx.get("llm").register_model_discovery("fixture", discover)
    try:
        assert await gateway.invoke({"namespace": "llm", "method": "listProviders", "args": {}}) == []
        args = {"settingsNs": "fixture", "request": {"provider": "fixture", "stripped": "extra"}}
        assert await gateway.invoke({"namespace": "llm", "method": "discoverModels", "args": args, "signal": signal}) == [{"id": "a"}]
        assert captured == [({"provider": "fixture"}, signal)]
        with pytest.raises(Exception) as caught:
            await gateway.invoke({"namespace": "llm", "method": "discoverModels", "args": {"settingsNs": "missing", "request": {"provider": "fixture"}}})
        failure = rpc_failure(caught.value)["error"]
        assert failure["code"] == "model-discovery-failed"
        assert failure["details"] == {"settingsNs": "missing"}
    finally:
        await ctx.fiber.dispose()
