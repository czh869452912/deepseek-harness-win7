"""Pair application-owned resource declarations through actual Gateway calls."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


def cases():
    return [dict(args=args, parameters=[dict(name=name, wire=wire) for name, wire in names]) for args, names in [
        (dict(sessionId='a', options=dict(sessionId='b')), [('sessionId','sessionId'),('options','options')]),
        (dict(target='a'), [('sessionId','target')]),
        (dict(options=dict(sessionId='a')), [('options','options')]),
        (dict(options=dict(address=dict(kind='session',sessionId='a'))), [('options','options')]),
        (dict(options=dict(address=dict(kind='subagent',parentSessionId='a',childSessionId='b'))), [('options','options')]),
        (dict(first={}, later=dict(sessionId='b')), [('first','first'),('later','later')]),
        (dict(count=1, tags=[], empty=None, options=dict(sessionId='a')), [(name,name) for name in ('count','tags','empty','options')]),
        ({}, []), ({}, [('sessionId','sessionId')]),
        (dict(options=dict(sessionId=None)), [('options','options')]),
        (dict(options=dict(sessionId='', address=None)), [('options','options')]),
        (dict(options=dict(sessionId='a', address=dict(kind='session',sessionId='b'))), [('options','options')]),
        (dict(options=dict(address={})), [('options','options')]),
        (dict(options=dict(address=None)), [('options','options')]),
        (dict(options=dict(address=dict(kind='other',childSessionId='b'))), [('options','options')]),
        (dict(options=dict(sessionId=3)), [('options','options')]),
        (dict(options=dict(sessionId=[])), [('options','options')]),
    ]]


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.core.session.json import UNDEFINED
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import remote_methods
    from dsh.host.connection.peer import Peer
    from dsh.api.session_current import CurrentSessionController
    from dsh.presets.registry_current import CurrentAgentPresetRegistry
    from dsh.subagent.service import SubagentRuntime
    from dsh.cordis.loader import Loader
    from scripts.rc022_subagent_fixture import setup
    rows=[]; capture=Context(); sentinel=RuntimeError('stop after resource registration')
    await capture.plugin(CurrentTypertRegistry)
    def stop(*_): raise sentinel
    capture.set_service('sessionProjections', NS(register=stop))
    try:
        try: CurrentSessionController(capture)
        except RuntimeError as error: assert error is sentinel
        resolver=capture.typert.resources.get('session')['resolve']
        for index, case in enumerate(cases()):
            try:
                value=resolver(case); answer=dict(value=None if value is UNDEFINED else value, absent=value is UNDEFINED)
            except Exception as error:
                answer=dict(error='coexisting' if 'must not contain both' in str(error) else 'invalid-address')
            rows.append(dict(name='reader:'+str(index), **answer))
    finally: await capture.fiber.dispose()
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx
    try:
        await ctx.plugin(CurrentTypertRegistry); await ctx.plugin(RemoteAccessService); await ctx.plugin(AuthorizedGatewayCore)
        await ctx.plugin(Loader); await ctx.plugin(CurrentAgentPresetRegistry, dict(default='coding'))
        await ctx.agentPresets.register(dict(id='coding', plugins=[]))
        for cls, names in [(ctx.agentPresets, ['select']), (ctx.subagents, ['prompt','interruptByUser'])]:
            for marker in remote_methods(cls):
                if marker['method'] in names:
                    readers=marker.get('resources', {})
                    rows.append(dict(name='marker:'+marker['method'], invocation=marker['invocation'], resource=readers['session'](dict(childSessionId='child')) if marker['method']=='prompt' else readers['session']('child') if readers else None))

        async def configure(child, agent): await ctx.agentPresets.mount(child, 'coding')
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model'),setup=configure))).agent
        await fixture.service.startActivation(dict(provider='spawn',parent=parent,childId='child',name='worker',label='Task',prompt=[dict(type='text',text='Task')],signal=fixture.signal,delivery='caller'))
        while ctx.agents.get('child').status!='running': await asyncio.sleep(0)
        held=[]; lookups=[]; received=[]
        ctx.remoteAccess.registerPolicy('guest', dict(bindings=lambda *_:[dict(resource=dict(kind='session',id=identity),role=dict(actions=['subagents/prompt','subagents/interruptByUser','agentPresets/select'])) for identity in held]))
        def lookup(identity): lookups.append(identity); return ctx.agents.get(identity)
        ctx.typert.lookups.configure('agent', lookup)
        ctx.on('agent/inbox/inserted',lambda payload:received.append(payload['message']['source']) if 'rpcId' in payload['message']['source'] else None)
        peer=Peer(ctx,dict(principal=dict(kind='guest',id='g')))
        async def invoke(name, namespace, method, args, grants):
            held[:]=grants; before=(len(lookups),len(received),parent.session.seq)
            try:
                value=await ctx.typertGateway.invoke(dict(namespace=namespace,method=method,args=args,peer=peer,signal=fixture.signal))
                result=dict(value=dict(accepted=bool(value['messageId'])) if method=='prompt' else value)
            except Exception as error: result=dict(error=dict(code=error.code,details=error.details))
            rows.append(dict(name=name,**result,lookupCount=len(lookups)-before[0],messages=len(received)-before[1],parentChanged=parent.session.seq!=before[2]))
        request=dict(requestId='rpc',childSessionId='child',sessionId='parent',delivery='queue',content=[dict(type='text',text='authorized')])
        await invoke('wrong-parent-grant','subagents','prompt',dict(request=request),['parent'])
        await invoke('target-grant','subagents','prompt',dict(request=request),['child'])
        rows.append(dict(name='attribution',source=received[-1]))
        await invoke('preset-denied','agentPresets','select',dict(agentId='parent',agentPreset='coding'),['child'])
        await invoke('preset-allowed','agentPresets','select',dict(agentId='parent',agentPreset='coding'),['parent'])
        await invoke('interrupt-denied','subagents','interruptByUser',dict(childSessionId='child'),['parent'])
        await invoke('interrupt-allowed','subagents','interruptByUser',dict(childSessionId='child'),['child'])
        await peer.dispose()
        return json.loads(json.dumps(rows))
    finally: await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'fixture.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),cases=cases())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_application_resources.mts','Actual Session resource registration seam/readers, actual preset/subagent markers, and actual Gateway+Agent+Loader+subagent provider calls with pre-lookup denial and durable caller attribution. Strict generated artifacts and whole Session owner filtering remain separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_resource.py',ROOT/'dsh/api/session_current.py',ROOT/'dsh/subagent/service.py',ROOT/'dsh/presets/registry_current.py'],prepare=prepare)
