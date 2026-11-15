"""Current job tools: single delivery, held reads and steer-aware waits."""
import math
import weakref

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.json_text import stringify_json
from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted,subscribe_abort
from dsh.core.tools import ToolArgsError
from dsh.llm.message import create_user_message
from .current import JobWaitAborted
from .render_current import blocks,public_job,status_line,read_body,summary,inline_notice,completion_notice,fit

SYSTEM_PROMPT_JOBS_TEXT=("Track every background job id you start. You are notified in-session when a job finishes — "
    "do not busy-poll or sleep on one; keep working on independent steps and do not duplicate a running job's work. "
    "Before giving a final answer, collect every still-relevant job with job_output "
    "(set wait: true only when you are genuinely blocked on it), and job_kill jobs that stopped mattering.")
PUBLIC_SCHEMA=dict(type='object',additionalProperties=False,properties=dict(
    id=dict(type='string'),kind=dict(type='string'),label=dict(type='string'),
    status=dict(type='string',enum=['running','stopping','completed','killed','failed']),
    detail=dict(type='string'),startedAt=dict(type='integer'),finishedAt=dict(type='integer')),
    required=['id','kind','label','status','startedAt'])


class CurrentToolJobs(Plugin):
    name='tool-jobs'
    inject=['tools','jobs','systemPrompt']
    Config=Schema.object(dict(waitTimeoutMs=Schema.number().min(1).default(30000),
        maxWaitTimeoutMs=Schema.number().min(1).default(600000),
        completionDelivery=Schema.union(['quiet','wakeup']).default('wakeup'),
        maxConsecutiveWakes=Schema.number().min(1),inlineOutputBytes=Schema.natural().default(2048)))

    def apply(self,ctx):
        config=self.config or {};jobs=ctx.jobs
        default=config.get('waitTimeoutMs',30000);cap=config.get('maxWaitTimeoutMs',600000)
        delivery=config.get('completionDelivery','wakeup');budget=config.get('maxConsecutiveWakes');inline_bytes=config.get('inlineOutputBytes',2048)
        if default>cap:raise ValueError('tool-jobs: waitTimeoutMs (%s) exceeds maxWaitTimeoutMs (%s)' % (default,cap))
        if budget is not None and (not math.isfinite(budget) or int(budget)!=budget or budget>9007199254740991):
            raise ValueError('tool-jobs: maxConsecutiveWakes (%s) must be a whole number of turns' % budget)
        spent=weakref.WeakKeyDictionary();pending={};limits=weakref.WeakKeyDictionary();killed=set();released={};suppressed={}
        if delivery=='wakeup' and budget is not None:
            def claimed(event):
                if event['message']['source']['kind']=='user':spent.pop(event['agent'],None)
            ctx.on('agent/inbox/claimed',claimed)
        def logged(session,event):
            if event['type']!='user/message' or event['data']['source']['kind']!='tool-jobs':return
            for identity,notice in list(pending.items()):
                if notice['messageId']==event['data']['id'] and notice['owner']==session.id and (notice['inline'] or 'held' not in notice):pending.pop(identity,None)
        ctx.on('session/event',logged)
        def visible_limit(execution):
            if execution.name not in ('job_output','job_kill') or not isinstance(execution.arguments,dict):return None
            identity=execution.arguments.get('job_id')
            if not isinstance(identity,str) or not identity:return None
            return next((job.get('outputLimitBytes') for job in jobs.list(execution.agent.id if execution.agent is not None else None) if job['id']==identity),None)
        async def pre_execute(execution,next_fn):
            maximum=visible_limit(execution)
            if maximum is not None:limits[execution]=maximum
            return await next_fn()
        ctx.on('tools/pre-execute',pre_execute,dict(prepend=True))
        def finalize(execution,result):
            maximum=limits.pop(execution,None)
            if maximum is None:maximum=visible_limit(execution)
            if maximum is None:return None
            content=result.content
            raw=content[0]['text'] if len(content)==1 and content[0].get('type')=='text' else None
            if execution.name=='job_output' and not result.is_error:
                value=result.value;body=value['text'] or '(no new output)';body=body[:-1] if body.endswith('\n') else body;suffix='\n'+status_line(value['job'])
                if raw==body+suffix:return blocks(fit(body,suffix,maximum,'\n[output truncated]'))
            return None if raw is None else blocks(fit(raw,'',maximum,'\n[result truncated]'))
        jobs.attachController('tool-jobs')
        ctx.systemPrompt.section(dict(name='tool:jobs',order=ctx.systemPrompt.getSectionOrder('TOOL_JOBS'),text=SYSTEM_PROMPT_JOBS_TEXT))

        def deliver(event):
            job=event['job']
            if event['cause']=='teardown' or 'owner' not in job:return
            agents=ctx.get('agents');owner=agents.get(job['owner']) if agents is not None else None
            if owner is None:return
            held=read_body(jobs.read(job['id'],job['owner']))['text'] if inline_bytes>0 and job['output']['total']<=inline_bytes else None
            inline=None if held is None else inline_notice(job,held,inline_bytes)
            message=create_user_message(dict(content=blocks(inline if inline is not None else completion_notice(job)),source=dict(kind='tool-jobs',form='notice',summary=summary(job['kind']+' '+job['label']+' '+status_line(public_job(job))))))
            pending[job['id']]=dict(owner=job['owner'],messageId=message['id'],inline=inline is not None,**({} if held is None else dict(held=held)))
            if delivery=='wakeup' and owner.status=='idle':
                count=spent.get(owner,0)
                if budget is None or count<budget:
                    if budget is not None:spent[owner]=count+1
                    owner.followup(message);return
            owner.inject(message)
        def begin_read(identity):
            claim=released.setdefault(identity,dict(pending=0));claim['pending']+=1
            def end():
                claim['pending']-=1
                if claim['pending']:return
                released.pop(identity,None);event=suppressed.pop(identity,None)
                if event is not None:deliver(event)
            return end
        def event_handler(event):
            if event['type']=='removed':
                killed.discard(event['job']['id']);pending.pop(event['job']['id'],None);return
            if event['type']!='settled':return
            identity=event['job']['id'];was_killed=identity in killed;killed.discard(identity)
            if was_killed or event['awaited']:return
            if identity in released:suppressed[identity]=event;return
            deliver(event)
        jobs.events.subscribe(dict(owners='scope'),event_handler)
        def identifier(args,name):
            identity=args['job_id']
            if not identity:raise ToolArgsError(name,['invalid job_id: expected a non-empty string, got '+stringify_json(identity)])
            return identity
        async def output(args,execution):
            identity=identifier(args,'job_output');timeout=args.get('timeout_ms')
            if timeout is not None and (type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0):
                raise ToolArgsError('job_output',['invalid timeout_ms: expected a positive number of milliseconds, got '+stringify_json(timeout)])
            agent=execution.agent;caller=agent.id if agent is not None else None;end=None;released_by=None
            try:
                if args.get('wait') is True:
                    input_signal=AbortController();combined=AbortController()
                    detach1=subscribe_abort(execution.signal,lambda _:combined.abort());detach2=subscribe_abort(input_signal.signal,lambda _:combined.abort())
                    def check():
                        nonlocal end,released_by
                        if agent is None or not any(message['source']['kind']=='user' for message in agent.inbox.nextStep):return
                        if end is None:end=begin_read(identity);released_by='user steered'
                        input_signal.abort()
                    def inserted(event):
                        if event['agent'] is agent:check()
                    unsubscribe=ctx.on('agent/inbox/inserted',inserted) if agent is not None else lambda:None
                    try:
                        check();await jobs.wait(identity,min(default if timeout is None else timeout,cap),caller,combined.signal)
                    except Exception:
                        if not input_signal.signal.aborted:raise
                        if aborted(execution.signal):raise JobWaitAborted()
                    finally:unsubscribe();detach1();detach2()
                body=read_body(jobs.read(identity,caller))
                if released_by is not None:suppressed.pop(identity,None)
                notice=pending.pop(identity,None)
                if notice is not None:
                    agents=ctx.get('agents');owner=agents.get(notice['owner']) if agents is not None else None
                    if owner is not None:owner.inbox.remove(notice['messageId'])
                    body['text']=notice.get('held','')+body['text']
                if released_by is not None and body['job']['status'] in ('running','stopping'):
                    body['job']['detail']=(body['job']['detail']+'; ' if 'detail' in body['job'] else '')+released_by
                return body
            finally:
                if end is not None:end()
        async def listing(args,execution):return [public_job(job) for job in jobs.list(execution.agent.id if execution.agent is not None else None)]
        async def kill(args,execution):
            identity=identifier(args,'job_kill');caller=execution.agent.id if execution.agent is not None else None
            result=jobs.kill(identity,caller,args.get('reason'))
            if result=='requested':killed.add(identity)
            return dict(outcome='already-finished' if result=='already-finished' else 'cancellation-requested',job=public_job(jobs.get(identity,caller)))
        def output_render(args,value):
            body=value['text'] or '(no new output)'
            return blocks(body+('' if body.endswith('\n') else '\n')+status_line(value['job']))
        common=dict(job_id=dict(type='string',required=True,description='Job id returned by the tool that started the background work.'))
        definitions=[dict(name='job_output',description='Read a background job: output since the previous read for stream jobs, or the result of a finished final-output job.',
            parameters=dict(common,wait=dict(type='boolean',description='Block until the job finishes or the timeout expires; a timed-out wait leaves the job running. Defaults to false.'),timeout_ms=dict(type='number',description='Max wait in milliseconds with wait: true. Defaults to and is capped by configuration.')),
            execute=output,finalizeContent=finalize,output=dict(schema=dict(type='object',additionalProperties=False,properties=dict(text=dict(type='string'),job=PUBLIC_SCHEMA),required=['text','job']),render=output_render),
            presentCall=lambda args:dict(card='generic',title='Read output from background job '+args['job_id'],kind='read',rawInput=args['job_id'])),
            dict(name='job_list',description='List your background jobs (running and finished) with their ids, kinds, and statuses.',parameters={},execute=listing,isConcurrencySafe=lambda *_:True,
                output=dict(schema=dict(type='array',items=PUBLIC_SCHEMA),render=lambda args,value:blocks('\n'.join('{id} [{kind}] {status} — {label}'.format(**job) for job in value) or '(no background jobs)')),
                presentCall=lambda _:dict(card='generic',title='List background jobs',kind='read')),
            dict(name='job_kill',description='Request cancellation of a running background job.',parameters=dict(common,reason=dict(type='string',description='Optional short reason, recorded in the log and forwarded to the job.')),execute=kill,finalizeContent=finalize,
                output=dict(schema=dict(type='object',additionalProperties=False,properties=dict(outcome=dict(type='string',enum=['cancellation-requested','already-finished']),job=PUBLIC_SCHEMA),required=['outcome','job']),render=lambda args,value:blocks('job '+value['job']['id']+' had already finished '+status_line(value['job']) if value['outcome']=='already-finished' else 'requested cancellation of job '+value['job']['id'])),
                presentCall=lambda args:dict(card='generic',title='Kill background job '+args['job_id'],kind='execute',rawInput=args['job_id']))]
        for definition in definitions:
            spec=definition['parameters']
            definition['parameters']=dict(type='object',properties={key:{name:value for name,value in item.items() if name!='required'} for key,item in spec.items()})
            required=[key for key,item in spec.items() if item.get('required')]
            if required:definition['parameters']['required']=required
            ctx.tools.register(definition)
