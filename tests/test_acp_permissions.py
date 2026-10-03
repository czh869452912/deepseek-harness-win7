import asyncio
import json
from types import SimpleNamespace

import pytest
import yaml

from dsh.acp.session_runtime import AcpSession
from dsh.acp.server import AcpPlugin
from dsh.acp.rpc import AcpRpc
from dsh.cordis.context import Context
from dsh.core.session import Session
from dsh.interaction.user_approval import ApprovalService
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import run_profile
from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter


@pytest.fixture
def permission_bridge():
    ctx = Context()
    service = ApprovalService(ctx)
    bridge = AcpPlugin()
    bridge.apply(ctx)
    session = Session('owned')
    agent = SimpleNamespace(id='owned', session=session)
    record = AcpSession(agent, ctx=ctx)
    bridge.sessions['owned'] = record
    session.append('turn/start', {'turn': 1})
    session.append('step/start', {'turn': 1, 'step': 1})
    return ctx, service, bridge, record, agent


@pytest.mark.asyncio
@pytest.mark.parametrize('answer,expected', [
    ({'outcome': {'outcome': 'selected', 'optionId': 'allow-once'}}, 'allowed-once'),
    ({'outcome': {'outcome': 'selected', 'optionId': 'reject-once'}}, 'rejected'),
    ({'outcome': {'outcome': 'selected', 'optionId': 'allow-always'}}, 'rejected'),
    ({'outcome': {'outcome': 'selected', 'optionId': True}}, 'rejected'),
    ({'outcome': {'outcome': 'cancelled'}}, 'cancelled'),
    ({'outcome': {'outcome': 'unknown', 'optionId': 'allow-once'}}, 'unavailable'),
    ({}, 'unavailable'), (None, 'unavailable'),
])
async def test_one_shot_permission_uses_actual_outgoing_wire_and_exact_owned_agent(permission_bridge, answer, expected):
    ctx, service, bridge, record, agent = permission_bridge
    output, emitted = [], asyncio.Event()
    def write(frame):
        output.append(json.loads(frame))
        emitted.set()
    bridge.connection = AcpRpc(write)
    try:
        decision = asyncio.create_task(service.request({'agent': agent, 'toolName': 'bash', 'callId': 'call-9'}))
        await asyncio.wait_for(emitted.wait(), 2)
        packet = output[0]
        assert packet == {'jsonrpc': '2.0', 'id': 0, 'method': 'session/request_permission', 'params': {
            'sessionId': 'owned', 'toolCall': {'toolCallId': 'call-9'}, 'options': [
                {'optionId': 'allow-once', 'name': 'Allow once', 'kind': 'allow_once'},
                {'optionId': 'reject-once', 'name': 'Reject', 'kind': 'reject_once'},
            ]}}
        bridge.connection.data(json.dumps({'jsonrpc': '2.0', 'id': 0, 'result': answer}) + '\n')
        assert await asyncio.wait_for(decision, 2) == expected
        decisions = [event['data'] for event in agent.session.events if event['type'] == 'approval/decided']
        assert decisions[-1]['outcome'] == expected
    finally:
        bridge.sessions.clear()
        bridge.connection.close()
        await bridge.connection.drain()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_permission_waits_committed_tool_update_and_rejects_disconnected_peer(permission_bridge):
    ctx, service, bridge, record, agent = permission_bridge
    output, release = [], asyncio.Event()
    bridge.connection = AcpRpc(lambda frame: output.append(json.loads(frame)))
    async def committed():
        await release.wait()
        await bridge.connection.notify('session/update', {'sessionId': 'owned', 'update': {
            'sessionUpdate': 'tool_call', 'toolCallId': 'call-9'}})
    record._queue(committed)
    try:
        decision = asyncio.create_task(service.request({'agent': agent, 'toolName': 'bash', 'callId': 'call-9'}))
        for iteration in range(10):
            await asyncio.sleep(0)
        assert output == [] and not decision.done()
        release.set()
        async def sent():
            while len(output) < 2:
                await asyncio.sleep(0)
        await asyncio.wait_for(sent(), 2)
        assert [frame['method'] for frame in output] == ['session/update', 'session/request_permission']
        bridge.connection.close()
        assert await asyncio.wait_for(decision, 2) == 'unavailable'
    finally:
        release.set()
        bridge.sessions.clear()
        bridge.connection.close()
        await bridge.connection.drain()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_same_id_foreign_agent_and_absent_call_id_delegate_without_request(permission_bridge):
    ctx, service, bridge, record, agent = permission_bridge
    output = []
    bridge.connection = AcpRpc(lambda frame: output.append(json.loads(frame)))
    try:
        foreign = SimpleNamespace(id='owned', session=agent.session)
        assert await service.request({'agent': foreign, 'toolName': 'bash', 'callId': 'call-9'}) == 'unavailable'
        assert await service.request({'agent': agent, 'toolName': 'bash'}) == 'unavailable'
        assert output == []
    finally:
        bridge.sessions.clear()
        bridge.connection.close()
        await bridge.connection.drain()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('choice,executions', [('allow-once', ['executed']), ('reject-once', [])])
async def test_canonical_agent_tool_permission_and_next_request_preserve_machine_decision(tmp_path, monkeypatch, choice, executions):
    home = tmp_path / 'home'
    profile = home / 'profiles' / 'permission-owned'
    init_profile(str(profile), [], 'startup')
    rows = [{'id': name, 'name': '@deepseek-ai/dsh-' + name} for name in
            ('session', 'tools', 'system-prompt', 'llm', 'agent', 'agent-loop', 'user-approval', 'acp')]
    rows.append({'id': 'persistence', 'name': '@deepseek-ai/dsh-session-persistence-jsonl',
                 'config': {'root': str(tmp_path / 'sessions'), 'packChunks': False}})
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    runtime = await run_profile({'profile': 'permission-owned', 'dshHome': str(home), 'args': [], 'waitForExit': False})
    ctx, output, effects = runtime['ctx'], [], []
    bridge = next(entry for entry in ctx.get('loader').entries
                  if entry.options.get('name') == '@deepseek-ai/dsh-acp').fiber.plugin
    bridge.connection = AcpRpc(lambda frame: output.append(json.loads(frame)))
    adapter = StrictMockLlmAdapter([{'tool_calls': [{'id': 'call-9', 'name': 'guarded_echo', 'arguments': {}}]},
                                   {'text': 'finished after decision'}])
    monkeypatch.setattr(ctx.get('llm'), 'chat_completion_stream', adapter.chat_completion_stream)
    async def execute(arguments, execution):
        effects.append('executed')
        return 'permission tool result'
    ctx.get('tools').register({'name': 'guarded_echo', 'description': 'Controlled approval fixture',
        'parameters': {'type': 'object', 'properties': {}}, 'execute': execute,
        'output': {'schema': {'type': 'string'}, 'render': lambda arguments, value: [{'type': 'text', 'text': value}]}})
    ctx.on('tools/pre-execute', lambda execution, next_fn: {'kind': 'ask'})
    try:
        created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
        session_id = created['sessionId']
        pending = asyncio.create_task(bridge.prompt(ctx, {'sessionId': session_id,
            'prompt': [{'type': 'text', 'text': 'request the controlled tool'}]}))
        async def requested():
            while not any(frame.get('method') == 'session/request_permission' for frame in output):
                assert not pending.done(), json.dumps([event for event in bridge.sessions[session_id].agent.session.events
                    if event['type'] in ('tool/result', 'approval/asked', 'approval/decided', 'agent/error')])
                await asyncio.sleep(.001)
        await asyncio.wait_for(requested(), 5)
        index = next(index for index, frame in enumerate(output) if frame.get('method') == 'session/request_permission')
        assert any(frame.get('method') == 'session/update' and frame['params']['update'].get('toolCallId') == 'call-9'
                   for frame in output[:index]), json.dumps(output)
        request = output[index]
        assert request['params']['sessionId'] == session_id and effects == []
        bridge.connection.data(json.dumps({'jsonrpc': '2.0', 'id': request['id'],
            'result': {'outcome': {'outcome': 'selected', 'optionId': choice}}}) + '\n')
        assert await asyncio.wait_for(pending, 5) == {'stopReason': 'end_turn'}
        assert effects == executions and len(adapter.requests) == 2
        next_messages = adapter.requests[1]['messages']
        assert any(block.get('type') == 'tool-result' for message in next_messages
                   for block in message.get('content', []) if isinstance(block, dict))
        assert ('permission tool result' in str(next_messages)) is bool(executions)
        agent = bridge.sessions[session_id].agent
        assert [event['data']['outcome'] for event in agent.session.events if event['type'] == 'approval/decided'] == [
            'allowed-once' if executions else 'rejected']
    finally:
        bridge.connection.close()
        await bridge.connection.drain()
        runtime['shutdown'].shutdown(0)
        await runtime['shutdown'].wait()
