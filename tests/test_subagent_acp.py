import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.subagent.acp import AcpProvider, CONFIG, SubagentAcp
from dsh.subagent.runtime import SubagentRuntime
from dsh.subprocess.local import LocalSubprocessRuntime


ROOT = Path(__file__).resolve().parents[1]
PEER = ROOT / 'scripts/oracles/subagent_acp_peer.py'


def request(cwd, controller=None):
    return {'parent': SimpleNamespace(session=SimpleNamespace(header={'cwd': str(cwd)})),
        'signal': (controller or AbortController()).signal,
        'prompt': [{'type': 'image', 'source': {'type': 'url', 'url': 'private-parent'}},
                   {'type': 'text', 'text': 'explicit child task'}]}


async def provider(tmp_path, env=None, policy='reject'):
    ctx = Context()
    await ctx.plugin(LocalSubprocessRuntime)
    config = CONFIG({'command': sys.executable, 'args': [str(PEER)],
        'env': dict(env or {}, PROBE_RECORD=str(tmp_path / 'wire.jsonl')),
        'permission': policy, 'disposeGraceMs': 100, 'disposeEofGraceMs': 150})
    return ctx, AcpProvider(ctx, config)


async def wait_file(path):
    deadline = asyncio.get_running_loop().time() + 8
    while not path.exists():
        assert asyncio.get_running_loop().time() < deadline, str(path)
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason, expected', [('end_turn', 'completed'), ('max_tokens', 'max-tokens'),
    ('refusal', 'refusal'), ('cancelled', 'aborted'), ('max_turn_requests', 'error')])
async def test_real_acp_child_output_protocol_and_terminal_reason(tmp_path, reason, expected):
    ctx, backend = await provider(tmp_path, {'PROBE_STOP': reason, 'PROBE_THOUGHT': '1'})
    run = None
    try:
        run = await backend.start(request(tmp_path))
        result = await asyncio.wait_for(asyncio.shield(run.result), 5)
        assert result['output'] == [{'type': 'text', 'text': 'child answer'}]
        assert result['stopReason'] == expected
        assert run.id != 'same-child-id' and run.localAgent is None
        if reason == 'max_turn_requests':
            assert result['diagnostic'] == 'Subagent failure (provider: ACP; stage: prompt; category: remote-limit; stop reason: max_turn_requests)'
        else:
            assert set(result) == {'output', 'stopReason'}
        await run.dispose()
        assert await run.child.wait_for_exit()
        assert (await run.child.done).exitCode == 0
        assert not run.rpc.pending and not run.rpc.tasks
        assert not run.request['signal']._listeners
        packets = [json.loads(line) for line in (tmp_path / 'wire.jsonl').read_text(encoding='utf-8').splitlines()]
        methods = {packet.get('method'): packet for packet in packets if 'method' in packet}
        assert methods['initialize']['params'] == {'protocolVersion': 1, 'clientCapabilities': {}}
        assert methods['session/new']['params'] == {'cwd': str(tmp_path), 'mcpServers': []}
        assert methods['session/prompt']['params'] == {'sessionId': 'same-child-id', 'prompt': [{'type': 'text', 'text': 'explicit child task'}]}
    finally:
        if run is not None:
            await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('policy, no_allow, expected', [('reject', False, 'denied'),
    ('allow', False, 'allowed'), ('allow', True, 'denied')])
async def test_actual_permission_decision_is_safe_and_first_allow_selected(tmp_path, policy, no_allow, expected):
    ctx, backend = await provider(tmp_path, {'PROBE_PERMISSION': '1', 'PROBE_IGNORE_PERMISSION': '1',
        'PROBE_NO_ALLOW': '1' if no_allow else '0', 'PROBE_TOOL_KIND': 'execute', 'PROBE_STOP': 'refusal'}, policy)
    run = None
    try:
        run = await backend.start(request(tmp_path))
        result = await run.result
        assert result == {'output': [{'type': 'text', 'text': 'child answer'}], 'stopReason': 'refusal',
            'diagnostic': 'ACP unattended decision (policy: {}; request: execute; decision: {})'.format(policy, expected)}
        await run.dispose()
        packets = [json.loads(line) for line in (tmp_path / 'wire.jsonl').read_text(encoding='utf-8').splitlines()]
        decision = next(packet['result'] for packet in packets if packet.get('id') == 'permission')
        assert decision == {'outcome': {'outcome': 'selected', 'optionId': 'first'}} if expected == 'allowed' else decision == {'outcome': {'outcome': 'cancelled'}}
    finally:
        if run is not None:
            await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_noncooperative_cancel_settles_partial_result_then_dispose_proves_exit(tmp_path):
    ready = tmp_path / 'ready'
    ctx, backend = await provider(tmp_path, {'PROBE_HANG': '1', 'PROBE_IGNORE_CANCEL': '1',
        'PROBE_IGNORE_EOF': '1', 'PROBE_READY': str(ready)})
    controller, run = AbortController(), None
    try:
        run = await backend.start(request(tmp_path, controller))
        await wait_file(ready)
        controller.abort('local cancel')
        assert await asyncio.wait_for(asyncio.shield(run.result), 1) == {
            'output': [{'type': 'text', 'text': 'child answer'}], 'stopReason': 'aborted'}
        assert not run.child.done.done()
        await asyncio.wait_for(run.dispose(), 5)
        assert await run.child.wait_for_exit() and run.child.done.done()
        assert run.reader.done() and not run.rpc.pending and not run.rpc.tasks
        await run.dispose()
    finally:
        if run is not None:
            await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_eof_flush_and_explicit_credentials_use_owned_subprocess_seam(tmp_path, monkeypatch):
    monkeypatch.setenv('AMBIENT_SECRET', 'private-parent-secret')
    flush = tmp_path / 'flush'
    ctx, backend = await provider(tmp_path, {'PROBE_FLUSH': str(flush), 'PROBE_ECHO_ENV': 'EXPLICIT_TOKEN', 'EXPLICIT_TOKEN': 'child-owned'})
    backend.config['disposeEofGraceMs'] = 1000
    run = None
    try:
        run = await backend.start(request(tmp_path))
        assert (await run.result)['output'] == [{'type': 'text', 'text': 'child-owned'}]
        await run.dispose()
        assert flush.read_text(encoding='utf-8') == 'flushed'
        assert (await run.child.done).exitCode == 0
    finally:
        if run is not None:
            await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_startup_abort_rolls_back_unpublished_real_child(tmp_path):
    ready, release = tmp_path / 'new-ready', tmp_path / 'new-go'
    ctx, backend = await provider(tmp_path, {'PROBE_NEW_READY': str(ready), 'PROBE_NEW_GO': str(release)})
    controller = AbortController()
    pending = asyncio.create_task(backend.start(request(tmp_path, controller)))
    try:
        await wait_file(ready)
        controller.abort('before publication')
        with pytest.raises(RuntimeError, match='aborted before the ACP child started'):
            await asyncio.wait_for(pending, 5)
        assert not ctx.get('subprocess').live
    finally:
        release.write_text('go', encoding='utf-8')
        await asyncio.gather(pending, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_safe_configuration_and_spawn_failure_do_not_leak_path(tmp_path):
    ctx, backend = await provider(tmp_path)
    try:
        missing = request(tmp_path)
        missing['parent'].session.header = {}
        with pytest.raises(RuntimeError) as failure:
            await backend.start(missing)
        assert str(failure.value) == 'subagent-acp: Subagent failure (provider: ACP; stage: initialize; category: configuration)'
        assert failure.value.cause is not None
        backend.config['command'] = str(tmp_path / 'private-token-no-executable')
        with pytest.raises(RuntimeError) as failure:
            await backend.start(request(tmp_path))
        assert str(failure.value) == 'subagent-acp: Subagent failure (provider: ACP; stage: process; category: process-start)'
        assert 'private-token' not in str(failure.value)
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_provider_registration_is_reversible_and_rejects_parent_capabilities(tmp_path):
    ctx = Context()
    await ctx.plugin(LocalSubprocessRuntime)
    await ctx.plugin(SubagentRuntime)
    mounted = await ctx.plugin(SubagentAcp, {'command': sys.executable, 'args': [str(PEER)]})
    try:
        runtime = ctx.get('subagents')
        assert runtime.getProvider('acp').inheritsParentContext is False
        assert set(runtime.getProvider('acp').capabilities.values()) == {False}
        with pytest.raises(RuntimeError, match='does not support'):
            await runtime.start('acp', dict(request(tmp_path), persona='parent override'))
        assert not ctx.get('subprocess').live
        await mounted.dispose()
        assert runtime.list() == []
    finally:
        await ctx.fiber.dispose()
