"""Regress real source observations and native ownership at the Inspect boundary."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from dsh.cordis.context import Context
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.session.json import UNDEFINED
from dsh.core.json_schema import assert_supported_json_schema, validate_json_schema_value
from dsh.core.tools import Tool
from dsh.extensions.inspect_registry import CordisInspectRegistryService
from scripts.inspect_oracle import classify, NATIVE_DISPOSAL, SOURCE_DISPOSAL
from scripts.oracles.inspect_python import observe, manifest

ROOT = Path(__file__).resolve().parents[1]
SPECS = json.loads((ROOT / 'scripts/oracles/inspect-cases.json').read_text(encoding='utf-8'))
FIXTURE = json.loads((ROOT / 'tests/fixtures/inspect-source-observations.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('spec,expected', list(zip(SPECS[:-1], FIXTURE['observations'])), ids=[spec['mode'] for spec in SPECS[:-1]])
async def test_inspect_real_source_observation(spec, expected):
    actual = await observe(spec)
    assert actual == (NATIVE_DISPOSAL if spec['mode'] == 'registry/disposal' else expected)


def test_inspect_source_receipts_are_bound_to_pinned_inputs():
    assert FIXTURE['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert len(FIXTURE['observations']) == len(SPECS) - 1
    assert [row['mode'] for row in FIXTURE['observations']] == [spec['mode'] for spec in SPECS[:-1]]
    for path, digest in FIXTURE['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


def test_unload_exception_gate_rejects_any_other_difference():
    assert classify(SOURCE_DISPOSAL, NATIVE_DISPOSAL) == 'reviewed-upstream-bug/INSPECT-001'
    assert classify(SOURCE_DISPOSAL, dict(NATIVE_DISPOSAL, result=None)) == 'different'
    assert classify(dict(SOURCE_DISPOSAL, extra=True), NATIVE_DISPOSAL) == 'different'
    assert classify(dict(SOURCE_DISPOSAL, mode='other'), dict(NATIVE_DISPOSAL, mode='other')) == 'different'


@pytest.mark.asyncio
async def test_caller_cancellation_retires_query_and_unsubscribes_signal():
    ctx = Context()
    registry = CordisInspectRegistryService(ctx)
    registry.syncClientManifest([manifest('client')])
    controller, owner = AbortController(), SimpleNamespace(id='owner')
    received = asyncio.Queue()
    ctx.on('cordis/inspect-query', received.put_nowait)
    try:
        task = asyncio.create_task(registry.query('client', 'client', 'read', UNDEFINED, owner, controller.signal))
        request = await asyncio.wait_for(received.get(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not registry._pending
        assert not controller.signal._listeners
        assert registry.resolveClientQuery(owner, request['requestId'], dict(ok=True, data=dict(value=1))) == dict(accepted=False)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_host_schema_borrowing_and_detached_output():
    ctx = Context()
    registry = CordisInspectRegistryService(ctx)
    descriptor = manifest()
    value = dict(value=1)
    dispose = registry.register(dict(manifest=descriptor, query=lambda *_: value))
    try:
        descriptor['description'] = 'mutated original'
        assert registry.list()[0]['description'] == 'Read-only probe'
        descriptor['methods'][0]['outputSchema']['properties']['value']['const'] = 2
        with pytest.raises(ValueError, match='returned invalid output'):
            await registry.query('host', 'probe', 'read', UNDEFINED, SimpleNamespace(id='owner'), NEVER_ABORTED)
        value['value'] = 2
        snapshot = await registry.query('host', 'probe', 'read', UNDEFINED, SimpleNamespace(id='owner'), NEVER_ABORTED)
        value['value'] = 3
        assert snapshot == dict(value=2)
        dispose(); dispose()
        assert registry.list() == []
    finally:
        descriptor['methods'][0]['outputSchema']['properties']['value'].pop('const', None)
        await ctx.fiber.dispose()


def test_deep_unions_are_stack_safe_and_keep_exact_one_matching():
    schema = dict(type='string')
    for _ in range(5000):
        schema = dict(oneOf=[schema, dict(type='null')])
    assert_supported_json_schema(schema)
    assert validate_json_schema_value(schema, 'leaf') == []
    assert validate_json_schema_value(schema, 42) == ['"value" must match exactly one oneOf branch (matched 0)']


def test_actual_tool_uses_source_implicit_root_diagnostics():
    tool = Tool('probe', 'Probe', dict(type='object', properties=dict(a=dict(type='integer')), required=['a']), lambda *_: None)
    assert tool.validate_arguments(dict(a=1.0)) == []
    assert tool.validate_arguments({}) == ['missing required property "a"']
    assert tool.validate_arguments(dict(a='bad')) == ['"a" must be an integer']
    assert tool.validate_arguments(None) == ['"arguments" must be an object']


def test_tools_exports_the_same_schema_contract_used_by_inspect():
    from dsh.core import tools
    from dsh.core import json_schema
    for name in ('JsonSchemaError', 'assertSupportedJsonSchema', 'assertObjectJsonSchema', 'validateJsonSchemaValue'):
        assert getattr(tools, name) is getattr(json_schema, name)
