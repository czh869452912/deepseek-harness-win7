import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session.json import FrozenDict, FrozenList
from dsh.typert.registry import TypertRegistry
from dsh.typert.remote import Remote, RemoteScope, TypertRemoteService, TypertLookupFailure
from dsh.typert.protocol import TypertLookupProvider
from dsh.typert.dispatch import RemoteDispatcher, TypertGatewayError, RemoteInvocationCancelled, rpc_failure
from dsh.typert.dispatch import assert_json
from dsh.typert.remote_events import lossless
from dsh.typert.artifact import Schema, UNDEFINED, read_generated_artifact

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SOURCE = json.loads((ROOT / 'tests/fixtures/remote-frozen-source-observations.json').read_text(encoding='utf-8'))


def test_frozen_remote_source_evidence_is_bound_to_actual_pinned_validators():
    assert FROZEN_SOURCE['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert len(FROZEN_SOURCE['observations']) == 16
    for path, digest in FROZEN_SOURCE['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


@pytest.mark.parametrize('row', FROZEN_SOURCE['observations'], ids=lambda row: row['container'] + '/' + row['recipe'])
def test_frozen_remote_matches_real_original_validator_observation(row):
    class ExoticObject(dict):
        pass
    class ExoticArray(list):
        pass
    leaf = {'valid-shared': FrozenDict(dict(nested=FrozenList([None, False, '中文', 42]))),
        'negative-zero': -0.0, 'infinity': float('inf'), 'nan': float('nan'),
        'undefined': UNDEFINED, 'exotic-object': ExoticObject(), 'exotic-array': ExoticArray(), 'cycle': {}}[row['recipe']]
    value = FrozenDict(dict(first=leaf, second=leaf)) if row['container'] == 'object' else FrozenList([leaf, leaf])
    if row['recipe'] == 'cycle':
        leaf['cycle'] = value
    try:
        lossless(value)
        accepted = True
    except ValueError:
        accepted = False
    assert accepted == row['session'] == row['gateway']


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


@pytest.mark.parametrize('freeze', [FrozenDict, FrozenList], ids=['object', 'array'])
def test_remote_json_accepts_only_internal_frozen_plain_containers(freeze):
    shared = FrozenDict(dict(nested=FrozenList([None, False, '中文', 42])))
    value = freeze(dict(first=shared, second=shared) if freeze is FrozenDict else [shared, shared])
    assert_json(value)
    lossless(value)
    with pytest.raises(TypeError, match='frozen'):
        value['new' if freeze is FrozenDict else 0] = None
    # A subclass can carry arbitrary behavior and is not the native freeze.
    class Exotic(freeze):
        pass
    with pytest.raises(ValueError, match='non-plain'):
        assert_json(Exotic(value))


@pytest.mark.parametrize('bad', [-0.0, float('inf'), float('nan'), UNDEFINED, object(), (1,)])
@pytest.mark.parametrize('freeze', [FrozenDict, FrozenList], ids=['object', 'array'])
def test_frozen_remote_data_still_rejects_lossy_or_non_json_leaves(freeze, bad):
    value = freeze(dict(nested=bad) if freeze is FrozenDict else [bad])
    with pytest.raises(ValueError):
        lossless(value)


@pytest.mark.asyncio
async def test_src_json_remote_result_can_be_a_frozen_tools_value():
    class FrozenExample(TypertRemoteService):
        def __init__(self, ctx):
            super().__init__(ctx, 'frozenExample')

        @Remote
        def read(self):
            return FrozenDict(dict(value=FrozenList([None, False, '中文', 42])))

    ctx = Context()
    try:
        await ctx.plugin(TypertRegistry)
        await ctx.plugin(FrozenExample)
        value = await RemoteDispatcher(ctx).invoke(dict(namespace='frozenExample', method='read', args={}))
        assert value == dict(value=[None, False, '中文', 42])
    finally:
        await ctx.fiber.dispose()


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
@pytest.mark.parametrize('explicit_implementation', [False, True])
async def test_strict_export_adapter_and_explicit_implementation_precedence(explicit_implementation):
    class Adapter(TypertRemoteService):
        def __init__(self, ctx):
            super().__init__(ctx, 'adapter')

        def read(self):
            raise AssertionError('Domain method must not become the wire export')

        @Remote('read')
        def wireRead(self):
            return dict(selected='export')

        def explicitRead(self):
            return dict(selected='explicit')

    ctx = Context()
    try:
        await ctx.plugin(TypertRegistry)
        await ctx.plugin(Adapter)
        row = dict(id='fixture#adapter/read', service='adapter', namespace='adapter', method='read',
                   invocation=dict(kind='direct'), parameters=[], result=dict(mode='src-json'))
        if explicit_implementation:
            row['implementation'] = 'explicitRead'
        ctx.get('typert').register(dict(package='fixture', face='host', schemas=[], model={}, invocations=[row]))
        assert await RemoteDispatcher(ctx).invoke(dict(namespace='adapter', method='read', args={})) == dict(
            selected='explicit' if explicit_implementation else 'export')
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_strict_duplicate_exports_reject_before_domain_invocation():
    class Ambiguous(TypertRemoteService):
        def __init__(self, ctx):
            super().__init__(ctx, 'ambiguous')

        def read(self):
            raise AssertionError('Ambiguous export must not invoke the domain')

        @Remote('read')
        def first(self):
            raise AssertionError('First export must not be selected silently')

        @Remote('read')
        def second(self):
            raise AssertionError('Second export must not be selected silently')

    ctx = Context()
    try:
        await ctx.plugin(TypertRegistry)
        await ctx.plugin(Ambiguous)
        row = dict(id='fixture#ambiguous/read', service='ambiguous', namespace='ambiguous', method='read',
                   invocation=dict(kind='direct'), parameters=[], result=dict(mode='src-json'))
        ctx.get('typert').register(dict(package='fixture', face='host', schemas=[], model={}, invocations=[row]))
        with pytest.raises(TypertGatewayError) as caught:
            await RemoteDispatcher(ctx).invoke(dict(namespace='ambiguous', method='read', args={}))
        assert caught.value.code == 'ambiguous-endpoint'
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
