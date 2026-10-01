"""Real canonical Web replacements for retired ApiProxy carrier tests.

No provider credentials or model calls are needed. This covers actual HTTP
ownership, scoped question responses and Session/Agent publication, rather
than treating the previous local HTTP/SSE bridge as an upstream contract.
"""
import asyncio
import json

import pytest

from canonical_web_fixture import web_context, close_web_context
from dsh.boot.plugin_registry import harness_plugin_spec
from dsh.core.abort import AbortController
from dsh.typert.artifact import UNDEFINED
from dsh.typert.dispatch import RemoteDispatcher
from dsh.typert.remote import TypertRemoteFailure


async def request(ctx, method, path, cookie=None, payload=None):
    port = ctx.get('webServer').listened_port
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    body = b'' if payload is None else json.dumps(payload).encode('utf-8')
    headers = ['Host: 127.0.0.1:%s' % port, 'Connection: close',
               'Content-Length: %s' % len(body), 'Content-Type: application/json']
    if cookie:
        headers.append('Cookie: ' + cookie)
    try:
        writer.write(('%s %s HTTP/1.1\r\n%s\r\n\r\n' %
                      (method, path, '\r\n'.join(headers))).encode('utf-8') + body)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), 5)
        head, content = raw.split(b'\r\n\r\n', 1)
        fields = {}
        for line in head.split(b'\r\n')[1:]:
            key, value = line.decode('latin-1').split(':', 1)
            fields[key.lower()] = value.strip()
        return int(head.split(b' ')[1]), fields, content
    finally:
        writer.close()
        await writer.wait_closed()


async def login(ctx):
    port = ctx.get('webServer').listened_port
    url = ctx.get('connection').authenticatedUrl('http://127.0.0.1:%s' % port)
    status, headers, _ = await request(ctx, 'GET', '/?' + url.split('?', 1)[1])
    assert status == 303
    return headers['set-cookie'].split(';', 1)[0]


async def call(ctx, namespace, method, **args):
    return await RemoteDispatcher(ctx).invoke(dict(namespace=namespace, method=method, args=args))


@pytest.mark.asyncio
async def test_original_remote_is_served_while_legacy_routes_are_unclaimed(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        assert harness_plugin_spec('@deepseek-ai/dsh-apiproxy') is None
        assert ctx.get('apiProxy') is None and ctx.get('api_proxy') is None
        cookie = await login(ctx)
        payload = dict(type='client-request', rpcId='inventory',
                       method='pluginInventory/list', payload=dict(args={}))
        # Authentication still fences the canonical /api owner over a real socket.
        assert (await request(ctx, 'POST', '/api/pluginInventory/list', payload=payload))[0] == 401
        status, _, body = await request(ctx, 'POST', '/api/pluginInventory/list', cookie, payload)
        assert status == 200
        result = json.loads(body)
        assert result['rpcId'] == 'inventory' and result['result']['ok'] is True
        assert result['result']['value']['entries']
        for method, path in [('GET', '/api/events/mux'), ('GET', '/api/events/host'),
                             ('POST', '/api/respond'), ('GET', '/api/status'),
                             ('GET', '/api/presets/list'), ('POST', '/api/plan/set'),
                             ('POST', '/api/goal/action'), ('POST', '/api/session.create'),
                             ('POST', '/api/host.pickDirectory')]:
            assert (await request(ctx, method, path, cookie, {}))[0] == 404, path
        assert '/api/remote.mux' in ctx.get('webServer')._upgrade_routes
        # Keep the actual client HMR SSE owner; it is independent of business streams.
        assert ctx.get('webServer').match('/plugins/events') is not None
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_canonical_session_and_fork_publish_only_complete_agents(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    states = []
    ctx.on('session/created', lambda session: states.append(
        (session.id, ctx.get('agents').get(session.id) is not None)))
    try:
        await call(ctx, 'session', 'create', request=dict(sessionId='web', cwd=str(tmp_path), agentPreset='minimal'))
        (tmp_path / 'other').mkdir()
        workspace = await call(ctx, 'workspace', 'create', request=dict(path=str(tmp_path / 'other')))
        wid = workspace['workspace']['workspaceId']
        await call(ctx, 'session', 'create', request=dict(sessionId='attached', workspaceId=wid, agentPreset='minimal'))
        # Canonical fork requires a completed turn, unlike the retired bridge's
        # unanchored synthetic copy. Prepare a real log boundary without a model call.
        agent = ctx.get('agents').get('web')
        agent.session.append('turn/start', {})
        agent.session.append_user_message('fork boundary')
        agent.session.append('turn/end', {})
        await agent.session.flush()
        fork = await call(ctx, 'session', 'fork', request=dict(sessionId='web'))
        assert ctx.get('agents').get(fork['sessionId']) is not None
        assert states == [('web', True), ('attached', True), (fork['sessionId'], True)]
        assert ctx.get('sessions').get('web').header.cwd == str(tmp_path)
        assert 'attached' in ctx.get('workspaceRegistry').get(wid).sessionIds
        before = list(states)
        with pytest.raises(TypertRemoteFailure):
            await call(ctx, 'session', 'create', request=dict(sessionId='rejected', cwd=str(tmp_path), agentPreset='absent'))
        assert states == before
        assert ctx.get('agents').get('rejected') is None
        assert ctx.get('sessions').get('rejected') is None
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_preset_authoring_and_nondefault_session_projection_use_actual_remotes(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    stream = None
    try:
        presets = await call(ctx, 'agentPresets', 'list')
        assert presets['authorable'] is True
        assert any(row['id'] == 'standard' and row['isDefault'] and row['trust'] == 'system'
                   for row in presets['presets'])
        assert await call(ctx, 'agentPresets', 'copy', **{'from': 'standard', 'id': 'custom-standard'}) is UNDEFINED
        document = await call(ctx, 'agentPresets', 'read', agentPreset='custom-standard')
        assert document['trust'] == 'user' and document['content']
        await call(ctx, 'session', 'create', request=dict(sessionId='selected', cwd=str(tmp_path), agentPreset='standard'))
        await call(ctx, 'session', 'create', request=dict(sessionId='other', cwd=str(tmp_path), agentPreset='minimal'))
        stream = await RemoteDispatcher(ctx).stream(dict(namespace='session', method='control', args={}, signal=AbortController().signal))
        assert (await stream.__anext__())['type'] == 'baseline'
        assert await call(ctx, 'agentPresets', 'select', agentId='selected', agentPreset='minimal') == 'minimal'
        async def projection():
            async for frame in stream:
                if frame['type'] == 'projection' and frame['key'] == 'agentPreset':
                    return frame
        frame = await asyncio.wait_for(projection(), 5)
        assert frame['sessionId'] == 'selected' and frame['value'] == 'minimal'
        assert ctx.get('sessionProjections').snapshot(ctx.get('agents').get('other').session)['values']['agentPreset'] == 'minimal'
        assert await call(ctx, 'agentPresets', 'deletePreset', id='custom-standard') is UNDEFINED
        assert all(row['id'] != 'custom-standard' for row in (await call(ctx, 'agentPresets', 'list'))['presets'])
    finally:
        if stream is not None:
            await stream.aclose()
        await close_web_context(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize('abort', [False, True])
@pytest.mark.parametrize('kind', ['question', 'tool', 'approval'])
async def test_scoped_human_request_uses_gateway_event_result_and_cancellation(tmp_path, abort, kind):
    ctx = await web_context(tmp_path / 'home')
    stream, task = None, None
    try:
        await call(ctx, 'session', 'create', request=dict(sessionId='question-owner', cwd=str(tmp_path), agentPreset='standard'))
        agent = ctx.get('agents').get('question-owner')
        gateway = ctx.get('typertGateway')
        stream = await gateway.open_wire_stream('$events', dict(args={}), AbortController().signal)
        ready = await stream.__anext__()
        signal = AbortController()
        question = dict(id='q1', question='Which mode?', options=[dict(label='Fast'), dict(label='Slow')])
        if kind in ('question', 'tool'):
            event, projected = 'user-questions/request', dict(questions=[question])
            if kind == 'question':
                action = agent.ctx.get('userQuestions').ask(dict(agent=agent, signal=signal.signal, **projected))
            else:
                tool = agent.ctx.get('tools').get_tool('ask_user_question', agent)
                assert tool is not None
                action = tool.handler(projected, agent=agent, signal=signal.signal)
        else:
            agent.session.append('turn/start', {})
            event, projected = 'approval/request', dict(toolName='pwsh', reason='Run reviewed command')
            action = agent.ctx.get('approval').request(dict(agent=agent, signal=signal.signal, **projected))
        task = asyncio.create_task(action)
        async def receive():
            async for frame in stream:
                if frame['type'] == 'waterfall':
                    return frame
        frame = await asyncio.wait_for(receive(), 5)
        assert frame['event'] == event and frame['agentId'] == agent.id
        assert frame['request'] == projected
        if abort:
            signal.abort(RuntimeError('caller stopped'))
            if kind in ('question', 'tool'):
                with pytest.raises(Exception) as raised:
                    await asyncio.wait_for(task, 5)
                assert raised.value.code == 'ASK_ABORTED'
            else:
                assert await asyncio.wait_for(task, 5) == 'cancelled'
            assert not gateway.events.pending
        else:
            cookie = await login(ctx)
            answer = 'allowed-once' if kind == 'approval' else dict(answers=[dict(id='q1', selected=['Fast'])])
            result = dict(clientId=ready['clientId'], eventId=frame['eventId'], outcome=dict(kind='result', value=answer))
            body = dict(type='client-request', rpcId='question-result', method='$events/result', payload=dict(args=result))
            status, _, response = await request(ctx, 'POST', '/api/$events/result', cookie, body)
            assert status == 200 and json.loads(response)['result'] == dict(ok=True)
            value = await asyncio.wait_for(task, 5)
            assert (json.loads(value) if kind == 'tool' else value) == answer
            assert not gateway.events.pending
        if kind == 'approval':
            audit = [entry for entry in agent.session.events if entry['type'].startswith('approval/')]
            assert [entry['type'] for entry in audit] == ['approval/asked', 'approval/decided']
            assert audit[0]['data']['id'] == audit[1]['data']['id']
            assert audit[1]['data']['outcome'] == ('cancelled' if abort else 'allowed-once')
            agent.session.append('turn/end', {})
            await agent.session.flush()
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if stream is not None:
            await stream.aclose()
        await close_web_context(ctx)
