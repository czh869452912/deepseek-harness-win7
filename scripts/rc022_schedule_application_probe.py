"""Real candidate Agent/Session Schedule deliveries with an explicit scripted LLM."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_application_probe as application
REQUESTS=[]


async def before(ctx,result,output):
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    class Adapter(ScriptAdapter):
        async def resolve_model(self,provider,model,signal=None):
            info=await super().resolve_model(provider,model,signal)
            info['context']=dict(contextWindow=131072)
            return info
        async def stream(self,request):
            REQUESTS.append(dict(provider=request.get('provider'),model=request.get('model')))
            yield dict(type='block-start',index=0,blockType='text')
            yield dict(type='text-delta',index=0,text='Scheduled work completed.')
            yield dict(type='finish',reason=dict(kind='stop'))
    ctx.llm.registerAdapter(['script'],Adapter({}))
    await ctx.get('agentDefaultModel').saveSelection(dict(provider='script',model='model'))


async def after(ctx,result,output):
    schedule=ctx.get('schedule');rows=[];result['scheduleDelivery']=rows
    async def delivered(id):
        async def wait():
            while True:
                entry=await schedule.view(dict(id=id))
                if 'lastDelivery' in entry:return entry
                await asyncio.sleep(.01)
        return await asyncio.wait_for(wait(),15)
    async def observe(entry,mode):
        receipt=entry['lastDelivery'];agent=ctx.agents.get(receipt['targetSessionId'])
        await asyncio.wait_for(agent.whenIdle(),15);await ctx.sessions.flush(agent.session)
        observed=await ctx.sessionQuery.observeSession(agent.session.id,dict(projectionMode='none'))
        try:
            messages=[event['data'] for event in observed.events if event['type']=='user/message' and event['data'].get('source',{}).get('kind')=='schedule']
            errors=[event['data'] for event in observed.events if event['type'] in ('turn/error','agent/error')]
            history=await schedule.history(dict(id=entry['id'],limit=10))
            rows.append(dict(mode=mode,status=entry['status'],target=entry['target'],scheduledAt=entry['scheduledAt'],receipt=receipt,
                persistedScheduleMessages=messages,turnErrors=errors,history=history,agentStatus=agent.status))
            assert len(messages)==1 and messages[0]['id']==receipt['messageId'] and not errors
        finally:observed.dispose()
    timed=await schedule.create(dict(title='Timed live delivery',prompt='Perform the timed check',timing=dict(kind='after',after_seconds=1),target=dict(kind='session',sessionId='candidate-minimal')),'candidate-minimal')
    await observe(await delivered(timed['id']),'timed-session')
    for kind in ['new_once','new']:
        entry=await schedule.create(dict(title='Independent '+kind,prompt='Perform the independent check',timing=dict(kind='after',after_seconds=3600),target=dict(kind=kind,create=dict(cwd=str(output),agentPreset='minimal'))),'candidate-minimal')
        ran=await schedule.run(dict(id=entry['id']));assert ran['scheduledAt']==entry['scheduledAt']
        await observe(ran,'manual-'+kind)
        pending=await schedule.run(dict(id=entry['id']));assert pending['code']=='schedule_execution_pending'
    result['scriptedModelRequests']=REQUESTS
    assert len(rows)==3 and REQUESTS


if __name__=='__main__':
    application.PLATFORM_PATCHES=[str(ROOT/'migration/candidates/rc022/win7-runtime.patch.yml')]
    application.EXECUTE_PTC=True;application.BEFORE_SESSIONS=before;application.AFTER_SESSIONS=after
    raise SystemExit(application.main())
