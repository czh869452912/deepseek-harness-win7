"""Current job tools with actual registry, pipeline, Agent inbox and Session."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_job_registry_probe import normalize
WORKSPACE=None


async def observe():
    from scripts.rc022_subagent_fixture import setup
    from dsh.jobs.current import CurrentLocalJobRegistry
    from dsh.jobs.tool_current import CurrentToolJobs
    from dsh.core.tools import ToolExecutionInput
    from dsh.core.abort import NEVER_ABORTED
    from dsh.llm.message import create_user_message
    fixture=await setup(WORKSPACE/'native',script=[]);ctx=fixture.ctx
    await ctx.plugin(CurrentLocalJobRegistry);await ctx.plugin(CurrentToolJobs,dict(completionDelivery='quiet',inlineOutputBytes=512))
    lease=await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')));agent=lease.agent;rows=[];futures=[];counter=0
    async def call(name,args):
        nonlocal counter
        counter+=1;result=await ctx.tools.execute(ToolExecutionInput('call-'+str(counter),name,args,agent=agent,signal=NEVER_ABORTED))
        return dict(isError=result.is_error,value=result.value,content=result.content)
    async def drain():
        for _ in range(10):await asyncio.sleep(0)
    def start(label,limit=None):
        future=asyncio.get_running_loop().create_future();futures.append(future);holder=[]
        def run(handle):holder.append(handle);return dict(done=future,cancel=lambda _:future.set_result(dict(status='killed')) if not future.done() else None)
        return ctx.jobs.start(dict(kind='pwsh',label=label,owner=agent.id,run=run,**({} if limit is None else dict(outputLimitBytes=limit)))),future,holder
    def notices():return [dict(content=message['content'],source=message['source']) for message in agent.inbox.nextStep if message['source']['kind']=='tool-jobs']
    try:
        identity,future,holder=start('stream');handle=holder[0];handle.append('out');handle.append('err',dict(channel='stderr'));handle.append('hidden',dict(channel='log'));handle.updateProgress('building')
        rows.append(dict(name='list-progress',value=await call('job_list',{})));rows.append(dict(name='live-read',value=await call('job_output',dict(job_id=identity))))
        future.set_result(dict(status='completed',result='FINAL'));await drain();rows.append(dict(name='inline-notice',notices=notices()))
        rows.append(dict(name='held-read',value=await call('job_output',dict(job_id=identity)),notices=notices()));rows.append(dict(name='repeat-read',value=await call('job_output',dict(job_id=identity))))
        ctx.jobs.remove(identity,agent.id)
        identity,future,holder=start('large-result');holder[0].append('head\n');future.set_result(dict(status='completed',result='R'*700));await drain()
        rows.append(dict(name='overflow-notice',notices=notices()));rows.append(dict(name='overflow-held',value=await call('job_output',dict(job_id=identity)),notices=notices()));ctx.jobs.remove(identity,agent.id)
        identity,future,holder=start('logged');holder[0].append('one time');future.set_result(dict(status='completed'));await drain()
        notice=next(message for message in agent.inbox.nextStep if message['source']['kind']=='tool-jobs');agent.session.append('user/message',notice,surface_op='append');agent.inbox.remove(notice['id'])
        rows.append(dict(name='logged-inline',value=await call('job_output',dict(job_id=identity))));ctx.jobs.remove(identity,agent.id)
        for limit in (1,7,8,16,40,64,100,300):
            identity,future,holder=start('  第一行\nsecond',limit);holder[0].append('你好'*100);future.set_result(dict(status='completed',result='R'*700));await drain()
            rows.append(dict(name='cap-'+str(limit),notices=notices(),value=await call('job_output',dict(job_id=identity))));ctx.jobs.remove(identity,agent.id)
        identity,future,holder=start('steer');holder[0].append('ready');holder[0].updateProgress('working')
        rows.append(dict(name='timeout',value=await call('job_output',dict(job_id=identity,wait=True,timeout_ms=1))))
        waiting=asyncio.create_task(call('job_output',dict(job_id=identity,wait=True,timeout_ms=10000)));await drain()
        agent.inject(create_user_message(dict(content=[dict(type='text',text='steer')],source=dict(kind='user'))))
        rows.append(dict(name='steered',value=await asyncio.wait_for(waiting,2),progress=ctx.jobs.get(identity,agent.id)['progress']))
        rows.append(dict(name='kill',value=await call('job_kill',dict(job_id=identity,reason='done'))));await ctx.jobs.wait(identity,10000,agent.id);await drain();rows.append(dict(name='no-kill-notice',notices=notices()));ctx.jobs.remove(identity,agent.id)
        return normalize(json.loads(json.dumps(rows)))
    finally:
        for future in futures:
            if not future.done():future.set_result(dict(status='killed'))
        await lease.dispose();await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_job_tools.mts','Actual current jobs/tool pipeline and persistent Agent Inbox: consuming versus listing reads, progress projection, stdout/stderr/log rendering, inline and held overflow notices, pending notice withdrawal, logged one-shot delivery, wait timeout, next-step user steer and model-requested cancellation suppression. Only job IDs and clocks normalized.',[Path(__file__).resolve(),ROOT/'dsh/jobs/tool_current.py',ROOT/'dsh/jobs/render_current.py'],prepare=prepare)
