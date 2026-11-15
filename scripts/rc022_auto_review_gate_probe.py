"""Real Cordis Auto plugin admission, review and shutdown contracts."""
import asyncio
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_auto_review_snapshot_probe import corpus as snapshot_cases


def corpus():
    return [dict(name=name) for name in ('allow','deny-ask','deny-never','deny-empty','deny-downstream','deny-downstream-ask',
        'allow-downstream-deny','allow-downstream-cancel','no-agent','non-auto','outer-code','inner','missing-facts','invalid-json-protocol',
        'provider-error','provider-typed-error','provider-nonerror','caller-aborted','unload-during-review','unload-during-next','root-shutdown','repeat','reinstall')]


async def observe():
    from types import SimpleNamespace as NS
    from dsh.cordis import Context
    from dsh.cordis.errors import ThrownValueError
    from dsh.cordis.awaiting import await_callback_result
    from dsh.core.abort import AbortController, abort_reason_error, NEVER_ABORTED
    from dsh.interaction.auto_review_current import CurrentAutoReview
    from dsh.llm.error import HarnessError
    rows=[]
    for item in corpus():
        name=item['name'];case=copy.deepcopy(next(c for c in snapshot_cases() if c['name']==('ptc-valid' if name=='inner' else 'native')))
        class Session:
            id='review-session'
            header=case['meta']
            surface=NS(nodes=case['nodes'])
            selected='workspace-write' if name=='non-auto' else 'auto'
            def snapshotEvents(self):return case['events']
            def requestHeader(self):return case['header']
            def isOwnSeq(self,seq):return seq>=case['own']
        session=Session();ctx=Context();calls=[];requests=[];signals=[];admission=[];available=[None];next_started=asyncio.Event();stream_started=asyncio.Event()
        caller=AbortController();caller_reason=RuntimeError('caller stopped')
        if name=='caller-aborted':caller.abort(caller_reason)
        async def directory(*_):calls.append('directory');return 'C:/gate'
        class Permission:
            def current(self,s):return s.selected
            def registerAuto(self,admit):
                def setup():
                    if available[0] is not None:raise RuntimeError('duplicate')
                    available[0]=admit
                    def stop():available[0]=None
                    return stop
                return ctx.effect(setup)
            def set(self,s,value):
                calls.append('select:'+value)
                try:available[0]()
                except Exception as error:admission.append(str(error))
                s.selected=value
        async def stream(options):
            calls.append('stream');signals.append(options['signal']);requests.append({key:value for key,value in options.items() if key!='signal'});stream_started.set()
            if name in ('unload-during-review','root-shutdown'):
                await options['signal'].wait_aborted()
                raise abort_reason_error(options['signal'])
            if name=='caller-aborted':raise abort_reason_error(options['signal'])
            if name=='provider-error':raise RuntimeError('provider secret')
            if name=='provider-typed-error':raise HarnessError('typed provider secret','PROVIDER')
            if name=='provider-nonerror':raise ThrownValueError('middleware refused')
            decision='deny' if name.startswith('deny') else 'allow'
            value=dict(risk='medium' if decision=='deny' else 'low',decision=decision)
            if name=='deny-empty':value['reason']=''
            elif decision=='deny':value['reason']='raw reason 🐱'
            if name=='invalid-json-protocol':value=dict(risk='high',decision='allow')
            text=json.dumps(value,ensure_ascii=False)
            yield dict(type='block-start',index=0,blockType='text')
            yield dict(type='block-end',index=0,block=dict(type='text',text=text))
            yield dict(type='finish',reason=dict(kind='stop'))
        services=dict(permissionPresets=Permission(),approval=NS(overrideOf=lambda _:'never' if name=='deny-never' else 'ask'),llm=NS(stream=stream),sessions=NS(list=lambda:[session]),tools=NS(),workingDirectory=NS(ensure=directory))
        for key,value in services.items():ctx.set_service(key,value)
        owner=await ctx.plugin(CurrentAutoReview)
        execution=dict(case['execution'],agent=None if name=='no-agent' else NS(session=session),signal=caller.signal)
        if name=='outer-code':execution['name']='run_code'
        if name=='missing-facts':case['header']=None
        async def next_fn(*_):
            calls.append('next');next_started.set()
            if name=='unload-during-next':await signals[-1].wait_aborted()
            kind='deny' if name in ('deny-downstream','allow-downstream-deny') else 'ask' if name=='deny-downstream-ask' else 'cancel' if name=='allow-downstream-cancel' else 'allow'
            return dict(kind=kind,reason='downstream') if kind in ('deny','ask') else dict(kind=kind)
        try:
            task=asyncio.ensure_future(ctx.waterfall('tools/pre-execute',execution,next_fn))
            if name in ('unload-during-review','root-shutdown'):
                await stream_started.wait()
                await (ctx.fiber.dispose() if name=='root-shutdown' else owner.dispose())
            elif name=='unload-during-next':
                await next_started.wait();await owner.dispose()
            result=await task
            second=await ctx.waterfall('tools/pre-execute',execution,next_fn) if name=='repeat' else None
            before=dict(selected=session.selected,available=available[0] is not None,signals=[s.aborted for s in signals])
            await owner.dispose()
            if name=='reinstall':
                owner=await ctx.plugin(CurrentAutoReview)
                calls.append('reinstalled')
            after=dict(selected=session.selected,available=available[0] is not None,signals=[s.aborted for s in signals],callerIdentity=all(s.reason is caller_reason for s in signals) if name=='caller-aborted' else None)
            rows.append(dict(name=name,result=result,second=second,before=before,after=after,calls=calls,admission=admission,requests=requests))
        finally:await ctx.fiber.dispose()
    from dsh.core.tools import ToolsService
    for name in ('allowed-once','rejected','cancelled','unavailable','missing-service','agentless','empty-reason','invalid'):
        requests=[]
        async def request(value):
            requests.append({key:val for key,val in value.items() if key not in ('agent','signal')})
            return 'unavailable' if name=='empty-reason' else name
        service=ToolsService.__new__(ToolsService);service.contract_version=4
        service._optional_service=lambda _:None if name in ('missing-service','empty-reason') else NS(request=request)
        execution=NS(name='probe',callId='call',agent=None if name=='agentless' else NS(),signal=NEVER_ABORTED,_approval_cancelled=False)
        ask=dict(kind='ask',reason='' if name=='empty-reason' else 'audit',displayReason=dict(en='Prompt',zh='提示'))
        try:result=dict(decision=await service._resolve_current_ask(execution,ask),approvalCancelled=execution._approval_cancelled)
        except Exception as error:result=dict(error=str(error))
        rows.append(dict(name='ask-'+name,result=result,requests=requests))
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.interaction.approval_current import CurrentApprovalService
    class Projections(Plugin):
        def apply(self,scope):SessionProjectionRegistry(scope,4)
    ctx=Context();await ctx.plugin(Projections)
    owner=await ctx.plugin(CurrentApprovalService,dict(policy='ask'))
    session=CurrentSession.create('provider',ctx=ctx,format_version=4)
    injected=[];answered=[]
    agent=NS(session=session,inject=lambda message:injected.append({key:value for key,value in message.items() if key!='id'}))
    service=ctx.approval;request=dict(agent=agent,toolName='probe',callId='call',reason='audit',displayReason=dict(en='Prompt',zh='提示'),signal=NEVER_ABORTED)
    ctx.on('approval/request',lambda value,next_fn:answered.append(dict(reason=value['reason'],displayReason=value['displayReason'])) or 'allowed-once')
    try:
        initial=service.projection.stateOf(session)
        try:await service.request(request)
        except Exception as error:idle_error=str(error)
        session.append('turn/start',dict(turn=1))
        allowed=await service.request(request)
        service.setPolicy(agent,'never');service.setPolicy(agent,'never')
        rejected=await service.request(request)
        session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
        final=service.projection.stateOf(session)
        events=[dict(type=event['type'],data={key:value for key,value in event['data'].items() if key!='id'}) for event in session.events if event['type'].startswith('approval/')]
        await owner.dispose()
        rows.append(dict(name='approval-provider',initial=initial,final=final,allowed=allowed,rejected=rejected,idleError=idle_error,events=events,injected=injected,answered=answered,withdrawn=ctx.get('approval') is None))
    finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8')
    snapshots=output/'snapshots.json';snapshots.write_text(json.dumps(snapshot_cases()),encoding='utf-8')
    return [path,snapshots]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_auto_review_gate.mts','Real Auto plugin over controlled Cordis collaborators: exact frozen review request and policy, bypasses, denial vs approval, downstream precedence, caller reason, active close/drain, admission veto, root shutdown preservation and reinstall.',[Path(__file__).resolve(),ROOT/'dsh/interaction/auto_review_current.py',ROOT/'dsh/interaction/auto_review_policy.json',ROOT/'dsh/interaction/auto_review_decision.py'],prepare=prepare)
