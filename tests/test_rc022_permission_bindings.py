import json

import pytest

from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.typert.artifact import read_generated_artifact
from scripts.oracles.agent_machine_current_python import ScriptAdapter
from scripts.rc022_candidate_fixture import setup
from test_rc022_manager_wire import http, SOURCE


@pytest.mark.asyncio
async def test_loader_permission_remote_command_review_and_retirement(tmp_path):
    requests = []; responses = []; executed = []
    class Reviewer(ScriptAdapter):
        async def stream(self, request):
            requests.append(request)
            yield dict(type='block-start', index=0, blockType='text')
            yield dict(type='block-end', index=0, block=dict(type='text', text=responses.pop(0)))
            yield dict(type='finish', reason=dict(kind='stop'))
    def prepare(ctx):
        for artifact in ('interaction/permission-presets', 'interaction/commands'):
            path = SOURCE / ('packages/' + artifact + '/lib/typert.host.js')
            ctx.inject(['typert'], lambda child, path=path: child.effect(lambda: child.typert.register(read_generated_artifact(path))))
        ctx.inject(['llm'], lambda child: child.llm.registerAdapter(['review'], Reviewer(dict(script=[]))))
        def tools(child):
            def execute(arguments, execution):
                executed.append(execution.callId)
                return 'published'
            child.tools.register(dict(name='probe', description='logged tool', parameters=dict(type='object'), execute=execute,
                output=dict(schema=dict(type='string'), render=lambda _args, value: [dict(type='text', text=value)])))
        ctx.inject(['tools'], tools)
    extra = [('subprocess-local', {}), ('sandbox-policy', dict(mode='workspace-write', workspaceRoot=str(tmp_path))),
        ('sandbox-local', {}), ('pwsh-sandbox', dict(cwd=str(tmp_path))), ('user-approval', dict(policy='ask')),
        ('permission-presets', {}), ('experimental-auto-review', {}), ('commands', {}),
        ('typert-registry', {}), ('api-remote-access', {}), ('api-gateway', dict(websocketCompression='none')),
        ('api-remotes', {}), ('credentials-local', dict(path=str(tmp_path/'credentials.yaml'))),
        ('client-connection', {}), ('host-webserver', dict(host='127.0.0.1', port=0))]
    ctx = await setup(tmp_path, extra=extra, prepare=prepare); lease = None
    observations = {}
    try:
        response = await http(ctx.webServer, '/connect?interactions=answer&token='+ctx.connection.browser_auth.launch_token)
        assert response['status'] == 302, response
        cookie = response['headers']['set-cookie'].split(';')[0]
        async def rpc(method, args):
            response = await http(ctx.webServer, '/api/'+method, dict(type='client-request', rpcId=method, method=method, payload=dict(args=args)), cookie)
            assert response['status'] == 200, response
            result = json.loads(response['body'])['result']
            assert 'error' not in result, result
            return result['value']
        catalog = await rpc('permissionPresets/catalog', {})
        observations['catalog'] = catalog
        assert catalog['defaultPreset'] == 'workspace-write'
        assert any(option['value'] == 'auto' for option in catalog['options'])
        lease = await ctx.agents.create(dict(sessionId='owner', agentOptions=dict(provider='review', model='m')))
        agent = lease.agent; session = agent.session
        assert ctx.permissionPresets.current(session) == 'workspace-write'
        switched = await rpc('commands/execute', dict(agentId='owner', line='/permission auto', submittedAttachments=[]))
        observations['command'] = switched
        assert switched['result'] == dict(kind='success', text='preset auto'), switched
        assert ctx.permissionPresets.current(session) == 'auto'
        observations['sandbox'] = ctx.sandboxPolicy.resolve(dict(session=session))
        assert observations['sandbox']['mode'] == 'danger-full-access'
        session.append('request/header', dict(header=dict(config=dict(provider='review', model='m'), tools=[dict(name='probe', description='logged tool', parameters=dict(type='object'))]), reason='initial'))
        session.append('user/message', dict(source=dict(kind='user'), content=[dict(type='text', text='Do the task')]), surface_op='append')
        session.append('turn/start', dict(turn=1))
        async def call(step, response):
            identity = 'call-'+str(step); responses.append(response)
            session.append('step/start', dict(turn=1, step=step))
            session.append('assistant/message', dict(turn=1, step=step, stream=[], message=dict(role='assistant', source=dict(kind='model', provider='review', model='m'), content=[dict(type='tool-call', id=identity, name='probe', arguments='{}')])), surface_op='append')
            session.append('tool/call', dict(turn=1, step=step, callId=identity, name='probe', arguments='{}'))
            result = await ctx.tools.execute(ToolExecutionInput(identity, 'probe', {}, agent=agent, signal=NEVER_ABORTED))
            session.append('step/end', dict(turn=1, step=step))
            return result
        allowed = await call(1, '{"risk":"low","decision":"allow"}')
        assert not allowed.is_error, allowed.error
        ctx.approval.setPolicy(agent, 'never')
        denied = await call(2, '{"risk":"high","decision":"deny","reason":"sensitive"}')
        assert denied.is_error and denied.error['info']['code'] == 'AUTO_REVIEW_DENIED'
        assert executed == ['call-1']
        assert len(requests) == 2 and all(request['purpose'] == 'auto-review' for request in requests)
        assert not any(event['type'] == 'request/header' and event['data']['header'].get('purpose') == 'auto-review' for event in session.events)
        entry = next(entry for entry in ctx.loader.entries() if entry.options.get('id') == 'experimental-auto-review')
        await await_callback_result(ctx.loader.update(entry.id, dict(disabled=True)))
        assert ctx.permissionPresets.current(session) == 'danger-full-access'
        retired = await rpc('permissionPresets/catalog', {})
        assert all(option['value'] != 'auto' for option in retired['options'])
        observations.update(retiredCatalog=retired, executed=executed, reviewPurposes=[request['purpose'] for request in requests], denied=denied.error,
            permissionEvents=[event for event in session.events if event['type'] in ('permission/preset', 'sandbox/mode', 'approval/policy')])
        (tmp_path/'permission-wire-observations.json').write_text(json.dumps(observations, indent=2), encoding='utf-8')
    finally:
        if lease is not None: await lease.dispose()
        await ctx.fiber.dispose()
