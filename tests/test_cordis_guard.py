"""Real source-boundary observations and guarded native Host integration."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from canonical_web_fixture import web_context, close_web_context
from dsh.core.abort import NEVER_ABORTED
from dsh.extensions.cordis_guard import sandbox_define_tool, sandbox_register_tool, clone_json
from scripts.cordis_guard_oracle import BUG_MODES, classify, corrected_observation
from scripts.oracles.cordis_guard_python import observe, definition

ROOT = Path(__file__).resolve().parents[1]
SPECS = json.loads((ROOT / 'scripts/oracles/cordis-guard-cases.json').read_text(encoding='utf-8'))
FIXTURE = json.loads((ROOT / 'tests/fixtures/cordis-guard-source-observations.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('spec,source', list(zip(SPECS, FIXTURE['observations'])), ids=[spec['mode'] for spec in SPECS])
async def test_real_guard_source_observation(spec, source):
    expected = corrected_observation(source) if spec['mode'] in BUG_MODES else source
    try:
        actual = dict(mode=spec['mode'], value=await observe(spec))
    except Exception as error:
        details = dict(message=getattr(error, 'message', str(error)))
        if getattr(error, 'code', None):
            details.update(code=error.code, name=error.name, violations=error.violations)
        actual = dict(mode=spec['mode'], error=details)
    assert actual == expected


def test_guard_source_observations_are_bound_to_pinned_inputs():
    assert FIXTURE['target_upstream'] == json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert len(SPECS) == len(FIXTURE['observations'])
    assert [row['mode'] for row in FIXTURE['observations']] == [spec['mode'] for spec in SPECS]
    for path, digest in FIXTURE['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest, path


def test_callable_context_exception_rejects_every_other_change():
    for source in FIXTURE['observations']:
        if source['mode'] not in BUG_MODES:
            continue
        corrected = corrected_observation(source)
        assert classify(source, corrected) == 'reviewed-upstream-bug/CORDIS-GUARD-001'
        assert classify(source, dict(corrected, extra=True)) == 'different'
        changed = copy.deepcopy(corrected)
        changed['value']['reports'] = []
        assert classify(source, changed) == 'different'
        assert classify(dict(source, mode='unreviewed'), corrected) == 'different'


@pytest.mark.asyncio
async def test_dynamic_json_clone_detaches_aliases_without_changing_shared_input():
    shared = dict(items=[1])
    options = definition()
    options['execute'] = lambda *_: dict(a=shared, b=shared)
    tool = sandbox_define_tool(options)
    result = await tool['execute']({}, {})
    assert result['a'] == result['b'] == shared
    assert result['a'] is not result['b'] and result['a'] is not shared
    result['a']['items'].append(2)
    assert shared == result['b'] == dict(items=[1])
    with pytest.raises(ValueError, match='harness.defineTool'):
        clone_json(tool, 'harness.defineTool definition')


@pytest.mark.asyncio
async def test_canonical_guarded_host_registers_executes_and_unwinds_tools(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='guard-owner', cwd=str(tmp_path), agentPreset='minimal'))
        owner, runner = ctx.get('agents').get('guard-owner'), ctx.get('dynamicCordisRunner')
        source = "def plugin(ctx):\n    tool = harness.defineTool({'name': 'guarded_echo', 'description': 'Echo', 'parameters': {'value': {'type': 'string', 'required': True}}, 'output': {'schema': {'type': 'string'}, 'render': lambda args, value: [{'type': 'text', 'text': value}]}, 'execute': lambda args, execution: args['value']})\n    ctx.tools.register(tool)\n    harness.handle('metadata', lambda args: ctx.tools.get('guarded_echo'))\nplugin.inject = ['tools']\n"
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='guard'), name='Guarded', purpose='real registration', code=dict(host=source)))
        started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
        assert started['ok'], started
        tools = ctx.get('tools')
        good = await tools.execute(dict(agent=owner, signal=NEVER_ABORTED, callId='guard-ok', name='guarded_echo', arguments=dict(value='ready')))
        assert good.content == [dict(type='text', text='ready')]
        assert not good.is_error
        invalid = await tools.execute(dict(agent=owner, signal=NEVER_ABORTED, callId='guard-invalid', name='guarded_echo', arguments=dict(value=3)))
        assert invalid.is_error
        meta = await runner.invoke(defined['pluginId'], started['pluginRunId'], 'metadata', {})
        assert meta['ok'] and set(meta['value']) == {'name', 'description', 'parameters'}
        assert meta['value']['parameters'] == dict(type='object', properties=dict(value=dict(type='string')), required=['value'])
        assert (await runner.stop(owner, defined['pluginId']))['ok']
        assert tools.get('guarded_echo') is None
        with pytest.raises(ValueError, match='harness.defineTool'):
            sandbox_register_tool(ctx, dict(name='raw'))
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_guard_runtime_context_return_reports_to_live_owner_without_stopping_run(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='guard-runtime', cwd=str(tmp_path), agentPreset='minimal'))
        owner, runner = ctx.get('agents').get('guard-runtime'), ctx.get('dynamicCordisRunner')
        messages = []
        # Observe the live Agent's notification boundary without starting a model turn.
        original_steer = owner.steer
        owner.steer = messages.append
        ctx.effect(lambda: lambda: setattr(owner, 'steer', original_steer))
        ctx.provide('guardCallable', lambda: ctx)
        source = "def plugin(ctx):\n    harness.handle('read', lambda args: ctx.get('guardCallable')())\n"
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='guard'), name='Runtime', purpose='real guard', code=dict(host=source)))
        started = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
        assert started['ok']
        for _ in range(2):
            failure = await runner.invoke(defined['pluginId'], started['pluginRunId'], 'read', {})
            assert failure['code'] == 'handler-error' and 'returned a cordis Context' in failure['message']
        assert len(messages) == 2  # One Guard diagnostic and one handler failure, each deduplicated.
        assert 'Cordis Host guard rejected runtime code' in messages[0]['content'][0]['text']
        assert runner.inventory()[0]['latestRun']['status'] == 'running'
        assert runner.inventory()[0]['activeRun']['pluginRunId'] == started['pluginRunId']
    finally:
        await close_web_context(ctx)
