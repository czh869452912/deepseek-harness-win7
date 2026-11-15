import gc
from types import SimpleNamespace as NS
import weakref

import pytest

from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.interaction.auto_review_current import CurrentAutoReview, _combined_signal
from dsh.interaction.permission_current import CurrentPermissionPresets
from dsh.interaction.approval_current import CurrentApprovalService
from scripts import rc022_auto_review_gate_probe as probe
from scripts.oracles.agent_machine_current_python import ScriptAdapter
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_cordis_gate_admission_cancellation_and_shutdown():
    rows={row['name']:row for row in await probe.observe()}
    assert len(rows)==32
    for name in ('allow','inner','repeat'):
        assert rows[name]['result']==dict(kind='allow')
    assert rows['deny-never']['result']['info']==dict(name='AutoReviewDeniedError',code='AUTO_REVIEW_DENIED',reason='raw reason 🐱')
    assert rows['deny-ask']['result']['kind']=='ask'
    assert rows['deny-empty']['result']['displayReason']['zh']=='Auto review 拒绝了此调用：'
    assert rows['deny-downstream']['result']==dict(kind='deny',reason='downstream')
    for name in ('no-agent','non-auto','outer-code'):
        assert rows[name]['requests']==[]
    for name in ('invalid-json-protocol','provider-error','provider-typed-error','provider-nonerror','caller-aborted','missing-facts'):
        assert rows[name]['result']['info']==dict(name='AutoReviewFailedError',code='AUTO_REVIEW_FAILED')
        assert 'next' not in rows[name]['calls']
    assert rows['provider-typed-error']['result']['reason'].endswith('typed provider secret')
    assert rows['provider-nonerror']['result']['reason'].endswith('middleware refused')
    assert rows['caller-aborted']['after']['callerIdentity']
    for name in ('unload-during-review','unload-during-next','root-shutdown'):
        assert rows[name]['result']==dict(kind='cancel')
    assert rows['root-shutdown']['after']['selected']=='auto'
    assert rows['unload-during-review']['after']['selected']=='danger-full-access'
    assert rows['reinstall']['after']['available'] and rows['reinstall']['after']['selected']=='danger-full-access'
    assert rows['unload-during-review']['admission']==['auto-review: integration is closing']
    assert rows['ask-rejected']['result']['decision']['info']==dict(name='ApprovalError',code='APPROVAL_REJECTED')
    assert rows['ask-cancelled']['result']['approvalCancelled']
    assert rows['ask-empty-reason']['result']['decision']['reason']==''
    assert rows['ask-allowed-once']['requests'][0]['displayReason']['zh']=='提示'
    provider=rows['approval-provider']
    assert provider['initial']==dict(policy=None,turnOpen=False)
    assert provider['final']==dict(policy='never',turnOpen=False)
    assert provider['allowed']=='allowed-once' and provider['rejected']=='rejected'
    assert len(provider['injected'])==1 and provider['injected'][0]['source']==dict(kind='user-approval')
    assert provider['withdrawn'] and len(provider['answered'])==1


@pytest.mark.asyncio
async def test_actual_agent_tool_runtime_permission_and_approval_integration(tmp_path):
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx
    lease=None
    try:
        ctx.set_service('shell',NS(sandboxMode='workspace-write'))
        await ctx.plugin(CurrentApprovalService,dict(policy='ask'))
        await ctx.plugin(CurrentPermissionPresets)
        auto=await ctx.plugin(CurrentAutoReview)
        requests=[];responses=[];executed=[];answers=[]
        class Reviewer(ScriptAdapter):
            async def stream(self,request):
                requests.append(request)
                value=responses.pop(0)
                yield dict(type='block-start',index=0,blockType='text')
                yield dict(type='block-end',index=0,block=dict(type='text',text=value))
                yield dict(type='finish',reason=dict(kind='stop'))
        ctx.llm.registerAdapter(['review'],Reviewer(dict(script=[])))
        class Probe(Plugin):
            inject=['tools']
            def apply(self,scope):
                def execute(arguments,execution):executed.append(execution.callId);return 'published'
                scope.tools.register(dict(name='probe',description='logged tool',parameters=dict(type='object'),execute=execute,
                    output=dict(schema=dict(type='string'),render=lambda _args,value:[dict(type='text',text=value)])))
        await ctx.plugin(Probe)
        ctx.on('approval/request',lambda request,next_fn:answers.append(request) or 'allowed-once')
        lease=await ctx.agents.create(dict(sessionId='review-runtime',agentOptions=dict(provider='review',model='m')))
        agent=lease.agent;session=agent.session
        ctx.permissionPresets.set(session,'auto')
        session.append('request/header',dict(header=dict(config=dict(provider='review',model='m'),tools=[dict(name='probe',description='logged tool',parameters=dict(type='object'))]),reason='initial'))
        session.append('user/message',dict(source=dict(kind='user'),content=[dict(type='text',text='Do the task')]),surface_op='append')
        session.append('turn/start',dict(turn=1))
        async def call(step,response):
            identity='call-'+str(step);responses.append(response)
            session.append('step/start',dict(turn=1,step=step))
            session.append('assistant/message',dict(turn=1,step=step,stream=[],message=dict(role='assistant',source=dict(kind='model',provider='review',model='m'),content=[dict(type='tool-call',id=identity,name='probe',arguments='{}')])),surface_op='append')
            session.append('tool/call',dict(turn=1,step=step,callId=identity,name='probe',arguments='{}'))
            result=await ctx.tools.execute(ToolExecutionInput(identity,'probe',{},agent=agent,signal=NEVER_ABORTED))
            session.append('step/end',dict(turn=1,step=step))
            return result
        assert ctx.permissionPresets.current(session)=='auto'
        result=await call(1,'{"risk":"low","decision":"allow"}')
        assert not result.is_error,result.error
        approved=await call(2,'{"risk":"medium","decision":"deny","reason":"review reason"}')
        assert not approved.is_error,approved.error
        assert len(answers)==1 and 'review reason' in answers[0]['reason']
        assert answers[0]['displayReason']['zh']=='Auto review 拒绝了此调用：review reason'
        ctx.approval.setPolicy(agent,'never')
        denied=await call(3,'{"risk":"high","decision":"deny","reason":"sensitive"}')
        assert denied.is_error and denied.error['info']['code']=='AUTO_REVIEW_DENIED'
        assert denied.error['info']['reason']=='sensitive'
        failed=await call(4,'{"risk":"high","decision":"allow"}')
        assert failed.is_error and failed.error['info']['code']=='AUTO_REVIEW_FAILED'
        assert executed==['call-1','call-2'] and len(answers)==1
        assert len(requests)==4 and all(request['purpose']=='auto-review' for request in requests)
        assert not any(event['type']=='request/header' and event['data']['header'].get('purpose')=='auto-review' for event in session.events)
        await auto.dispose()
        assert ctx.permissionPresets.current(session)=='danger-full-access'
        assert 'auto' not in ctx.permissionPresets.names
        replacement=await ctx.plugin(CurrentAutoReview)
        assert ctx.permissionPresets.current(session)=='danger-full-access'
        await replacement.dispose()
    finally:
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()


def test_combined_signal_retained_identity_and_unretained_listener_cleanup():
    one,two=AbortController(),AbortController()
    signal=_combined_signal(one.signal,two.signal);reason=RuntimeError('stop')
    two.abort(reason)
    assert signal.aborted and signal.reason is reason
    one,two=AbortController(),AbortController()
    signal=_combined_signal(one.signal,two.signal);reference=weakref.ref(signal)
    assert one.signal._listeners and two.signal._listeners
    del signal;gc.collect()
    assert reference() is None
    assert not one.signal._listeners and not two.signal._listeners
