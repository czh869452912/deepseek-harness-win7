"""Pair decision, filtering and streaming access snapshots against fixed Source."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
GUEST=dict(kind='guest',guest='a')
GLOBAL=dict(kind='global')
ROOM=dict(kind='session',id='a')
OTHER=dict(kind='session',id='b')


def cases():
    def binding(resource,actions=None,condition=None):
        value=dict(resource=resource,role=dict(name='fixture',resource=resource['kind'],actions=actions or ['notes/read']))
        if condition is not None:value['condition']=condition
        return value
    grant=binding(ROOM)
    return [
        dict(name='owner',principal=dict(kind='owner'),bindings=[],resources=[ROOM]),
        dict(name='snapshot-exemption',action='remoteAccess/follow',bindings=[],resources=[GLOBAL]),
        dict(name='absent-policy',principal=dict(kind='unknown'),bindings=[grant],resources=[ROOM]),
        dict(name='bound',bindings=[grant],resources=[ROOM]),
        dict(name='different-resource',bindings=[grant],resources=[OTHER]),
        dict(name='global-does-not-imply-room',bindings=[binding(GLOBAL)],resources=[ROOM]),
        dict(name='every-resource',bindings=[grant],resources=[ROOM,OTHER]),
        dict(name='empty-resources',bindings=[],resources=[]),
        dict(name='first-refusal',bindings=[binding(ROOM,condition=['deny','first']),binding(ROOM,condition=['deny','second'])],resources=[ROOM]),
        dict(name='later-allow',bindings=[binding(ROOM,condition=['deny','first']),grant],resources=[ROOM]),
        dict(name='allowing-condition',bindings=[binding(ROOM,condition=['allow'])],resources=[ROOM]),
        dict(name='condition-args',bindings=[binding(ROOM,condition=['args'])],resources=[ROOM],args=dict(text='allowed')),
        dict(name='condition-no-args',bindings=[binding(ROOM,condition=['args'])],resources=[ROOM]),
        dict(name='unmatched-condition-does-not-run',bindings=[binding(OTHER,condition=['throw']),grant],resources=[ROOM]),
        dict(name='explain',bindings=[],resources=[ROOM],explain='expired'),
        dict(name='condition-before-explain',bindings=[binding(ROOM,condition=['deny','condition'])],resources=[ROOM],explain='explanation'),
        dict(name='bindings-failed',bindings=[],resources=[ROOM],failure='bindings'),
        dict(name='condition-failed',bindings=[binding(ROOM,condition=['throw'])],resources=[ROOM]),
        dict(name='explain-failed',bindings=[],resources=[ROOM],failure='explain'),
        dict(name='snapshot-grouping',bindings=[binding(ROOM,['notes/z','event:notice','notes/a','notes/z']),binding(ROOM,['notes/b']),binding(OTHER,['notes/a'],['deny','paused'])],resources=[ROOM],action='notes/a'),
    ]


def condition(spec):
    def decide(request):
        if spec[0]=='throw':raise RuntimeError('private fixture condition')
        if spec[0]=='allow':return dict(kind='allow')
        if spec[0]=='args':return dict(kind='allow') if request.get('args',{}).get('text')=='allowed' else dict(kind='deny',reason='requires-args')
        return dict(kind='deny',reason=spec[1])
    return decide


async def observe():
    from types import SimpleNamespace as NS
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.core.session.json import UNDEFINED
    ctx=Context();owner=await ctx.plugin(RemoteAccessService);access=ctx.remoteAccess;rows=[];state={};calls=[]
    def bindings(principal):
        calls.append(principal)
        if state.get('failure')=='bindings':raise RuntimeError('private fixture bindings')
        return state['bindings']
    def explain(request):
        if state.get('failure')=='explain':raise RuntimeError('private fixture explain')
        return state.get('explain',UNDEFINED)
    try:
        access.registerPolicy('guest',NS(bindings=bindings,explain=explain))
        for case in cases():
            state.clear();state.update(case)
            state['bindings']=[dict(binding,**(dict(condition=condition(binding['condition'])) if 'condition'in binding else {})) for binding in case['bindings']]
            access.invalidate();before=len(calls)
            request=dict(principal=case.get('principal',GUEST),action=case.get('action','notes/read'),resources=case['resources'])
            if 'args'in case:request['args']=case['args']
            decision=access.decide(request);count=len(calls)-before
            invocation=dict(peer=dict(principal=request['principal']),request=dict(namespace='notes',method='read'))
            scoped=ctx.extend(dict(invocation=invocation)).remoteAccess
            rows.append(dict(name=case['name'],decision=decision,bindingCalls=count,filtered=[resource for resource in [ROOM,OTHER] if scoped.allows(resource)],snapshot=access.snapshotFor(request['principal'])))
        state.clear();state['bindings']=[];access.invalidate()
        invocation=dict(peer=dict(principal=GUEST),request=dict(namespace='remoteAccess',method='follow'))
        control=AbortController();stream=ctx.extend(dict(invocation=invocation)).remoteAccess.follow(control.signal)
        frames=[await stream.__anext__()]
        state['bindings']=[dict(resource=ROOM,role=dict(actions=['notes/read','event:notice']))]
        # Equal principals with reversed key order invalidate the same generation.
        access.invalidate(dict(guest='a',kind='guest'))
        frames.append(await stream.__anext__())
        state['bindings']=[dict(resource=OTHER,role=dict(actions=['notes/write']))]
        access.invalidate(GUEST)
        frames.extend([await stream.__anext__(),await stream.__anext__()])
        pending=asyncio.create_task(stream.__anext__());await asyncio.sleep(0)
        access.invalidate(dict(kind='guest',guest='other'));await asyncio.sleep(0)
        unaffected=not pending.done();control.abort()
        try:await pending
        except StopAsyncIteration:pass
        rows.append(dict(name='follow',frames=frames,unaffected=unaffected,followers=len(access.followers),listeners=len(control.signal._listeners)))
        control=AbortController();stream=access.follow(control.signal);baseline=await stream.__anext__()
        pending=asyncio.create_task(stream.__anext__());await asyncio.sleep(0);await owner.dispose()
        try:await pending
        except StopAsyncIteration:pass
        rows.append(dict(name='owner-unload',baseline=baseline,listeners=len(control.signal._listeners)))
        return json.loads(json.dumps(rows))
    finally:await ctx.fiber.dispose()


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_remote_access.mts','Resource-specific allow/deny, one binding read per decision, condition/explain precedence and contained failures, per-item invocation filtering, grouped snapshots, follow deltas/coalescing/principal identity/cancellation/unload.',
        [Path(__file__).resolve(),ROOT/'dsh/typert/remote_access.py'],prepare=prepare)
