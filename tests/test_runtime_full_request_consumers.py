import copy
import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.runtime_full_request_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import full_request_receipts


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('provider', 'system', 'tools', 'assistant-alias', 'token-alias', 'reasoning-alias',
    'message-owner', 'signal-owner', 'signal-state', 'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes')


@pytest.fixture(scope='module')
def actual_pair(tmp_path_factory):
    output = tmp_path_factory.mktemp('runtime-full-request-pair') / 'paired.json'
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/runtime_full_request_oracle.py'),
        '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
    (output.parent / 'runner.log').write_bytes(completed.stdout + completed.stderr)
    assert completed.returncode == 0, output.read_text(encoding='utf-8')
    return (json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
        json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('name', NAMES)
def test_actual_complete_agent_model_requests_match_source(name, actual_pair):
    from scripts.runtime_full_request_oracle import canonical
    source, native = actual_pair
    assert canonical(next(row for row in native['observations'] if row['name'] == name)) == canonical(
        next(row for row in source['observations'] if row['name'] == name))


@pytest.mark.parametrize('damage', DAMAGES)
def test_full_request_receipt_requires_complete_graph_and_runtime(actual_pair, tmp_path, damage):
    source, original = actual_pair
    runtime = copy.deepcopy(original)
    modules = original['modules'].copy()
    row = runtime['observations'][0]
    if damage == 'provider':
        row['requests'][0]['provider'] = 'foreign'
    elif damage == 'system':
        row['requests'][1]['system'] = 'foreign'
    elif damage == 'tools':
        row['requests'][1]['tools'][0]['parameters']['additionalProperties'] = True
    elif damage == 'assistant-alias':
        next(message for message in row['requests'][1]['messages'] if message['role'] == 'assistant')['tool_calls'] = []
    elif damage == 'token-alias':
        next(row for row in runtime['observations'] if row['name'] == 'change/max-tokens')['requests'][0]['max_tokens'] = 17
    elif damage == 'reasoning-alias':
        next(row for row in runtime['observations'] if row['name'] == 'change/reasoning')['requests'][0]['reasoning_effort'] = 'high'
    elif damage == 'message-owner':
        row['requests'][1]['messages'][0]['id'] = 'foreign-detached-id'
    elif damage == 'signal-owner':
        row['requests'][1]['signal']['sameAsFirst'] = False
    elif damage == 'signal-state':
        row['requests'][0]['signal']['aborted'] = True
    elif damage == 'tail':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][-1] = copy.deepcopy(runtime['observations'][0])
    elif damage == 'root':
        runtime['root'] = str(tmp_path)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'python.exe')
    elif damage == 'module':
        del runtime['modules']['dsh/llm/llm_service.py']
    else:
        modules['dsh/llm/llm_service.py'] = '0' * 64
        runtime['modules'] = modules.copy()
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(runtime, ROOT, identity(source), modules)


@pytest.mark.parametrize('damage', ['pin', 'node', 'inputs', 'bytes'])
def test_full_request_source_identity_is_required(actual_pair, damage):
    source = copy.deepcopy(actual_pair[0])
    if damage == 'pin':
        source['sourceCommit'] = '0' * 40
    elif damage == 'node':
        source['node'] = 'v22.20.0'
    elif damage == 'inputs':
        del source['inputs']['reference/packages/llm/llm/src/types.ts']
    else:
        source['inputs']['reference/packages/llm/llm/src/types.ts'] = '0' * 64
    with pytest.raises(ValueError):
        identity(source)


@pytest.mark.parametrize('side', ['source', 'native'])
def test_portable_full_request_cli_refuses_partial_receipts(tmp_path, side):
    with pytest.raises(RuntimeError, match='Both runtime full request'):
        full_request_receipts(str(tmp_path / 'source.json') if side == 'source' else None,
            str(tmp_path / 'native.json') if side == 'native' else None, tmp_path / 'output.json')


@pytest.mark.asyncio
@pytest.mark.parametrize('configuration', ['max-tokens', 'reasoning', 'both'])
async def test_actual_fixed_parameter_adapter_keeps_python_boundary_arguments(configuration):
    from dsh.cordis import Context
    from dsh.core.agent import AgentOptions
    from dsh.core.agent_loop import AgentLoopPlugin

    class LegacyModel:
        provider, model = 'mock', 'mock'

        def __init__(self):
            self.requests = []

        async def chat_completion_stream(self, messages, tools=None, system=None, max_tokens=None, reasoning_effort=None):
            self.requests.append(dict(max_tokens=max_tokens, reasoning_effort=reasoning_effort))
            yield dict(type='block-start', index=0, blockType='text')
            yield dict(type='block-end', index=0, block=dict(type='text', text='finished'))
            yield dict(type='finish', reason=dict(kind='stop'))

    tokens = 17 if configuration in ('max-tokens', 'both') else None
    effort = 'high' if configuration in ('reasoning', 'both') else None
    ctx = Context()
    model = LegacyModel()
    ctx.set_service('llm', model)
    await ctx.plugin(AgentLoopPlugin)
    parent = await ctx.get('agent_loop').create('parent', options=AgentOptions(provider='mock', model='mock',
        max_tokens=tokens, reasoning_effort=effort))
    try:
        parent.agent.followup('check legacy parameters')
        await asyncio.wait_for(parent.agent.when_idle(), 10)
        assert model.requests == [dict(max_tokens=tokens, reasoning_effort=effort)]
        assert next(event for event in parent.agent.session.events if event['type'] == 'turn/end')['data']['reason']['kind'] == 'completed'
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()
