"""Host timer over durable tasks; only delivery activates a Session."""
import asyncio
import inspect
import time
import uuid

from dsh.cordis.awaiting import start_coroutine,await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_error_to_string
from dsh.llm.message import create_user_message
from dsh.schedule.domain_current import (
    is_recurring_schedule_record,resolve_recurring_occurrence,
    render_reminder_framing,render_recurring_reminder_batch_framing,format_schedule_local_time,
)
from dsh.schedule.delivery_history_current import append_delivery
from dsh.session.persistence import SessionPersistenceNotFoundError
from dsh.typert.remote import RemoteError
from dsh.typert.stores import field
from dsh.util_time_instant import four_digit_year_epoch,format_four_digit_year_instant

MAX_TIMER_DELAY_MS=2147483647
MIN_DELIVERY_INTERVAL_MS=60000


def now_ms():return int(time.time()*1000)
def iso(epoch):return format_four_digit_year_instant(epoch)
def epoch(value):return four_digit_year_epoch(value)['epoch']
def batch_session_of(task):
    return task['target']['sessionId'] if task['target']['kind']=='session' and is_recurring_schedule_record(task['record']) else None


def observed_future(value):
    future=start_coroutine(value) if inspect.iscoroutine(value) else asyncio.ensure_future(value)
    future.add_done_callback(lambda done:done.exception() if not done.cancelled() else None)
    return future


class CurrentScheduleRuntime:
    def __init__(self,ctx,tasks,transact,commit,changed,limits,resolve_agent):
        self.ctx=ctx;self.tasks=tasks;self.transact=transact;self.commit=commit;self.changed=changed
        self.limits=limits;self.resolve_agent=resolve_agent
        self.timer=None;self.running=None;self.executing=set();self.stopping=False;self.requested=False

    def clear_timer(self):
        if self.timer is not None:self.timer.cancel()
        self.timer=None

    def request_drive(self):
        if self.stopping:return
        self.requested=True;self.clear_timer()
        if self.running is not None:return
        async def drive_loop():
            while self.requested and not self.stopping:
                self.requested=False
                await await_callback_result(self.transact(self.drive))
        try:run=observed_future(self.ctx.get('agents').withoutInitiator(drive_loop))
        except Exception as error:
            self.requested=False;self.ctx.logger.warn('schedule: dispatch stopped: '+_js_error_to_string(error));return
        self.running=run
        def settled(done):
            if not done.cancelled() and done.exception() is not None:
                self.ctx.logger.warn('schedule: dispatch stopped: '+_js_error_to_string(done.exception()))
            self.running=None
            if self.requested and not self.stopping:self.request_drive()
        run.add_done_callback(settled)

    requestDrive=request_drive

    async def dispose(self):
        self.stopping=True;self.clear_timer()
        if self.running is not None:
            await asyncio.gather(asyncio.shield(self.running),return_exceptions=True)

    async def run_now(self,id,signal=None):
        async def work():
            if signal is not None:signal.throwIfAborted()
            task=next((task for task in self.tasks() if task['record']['id']==id),None)
            if task is None:return None
            if id in self.executing or self.next_admission_at(task)>now_ms() or await self.recover_outstanding_execution(task):
                return dict(task=task,admitted=False)
            target=await self.resolve_target(task)
            if self.stopping:raise RuntimeError('Schedule runtime is stopping')
            occurrence_at=iso(now_ms());held=[id] if task['target']['kind']!='new' else []
            sent=await self.send(target['agent'],render_reminder_framing(dict(task['record'],scheduledAt=occurrence_at)),held)
            committed=set()
            try:
                delivered=self.delivered(task,dict(scheduledAt=occurrence_at,deliveredAt=sent['deliveredAt'],messageId=sent['messageId'],targetSessionId=target['sessionId']))
                await await_callback_result(self.commit(delivered));committed.add(id)
                return dict(task=delivered,admitted=True)
            finally:self.settle(held,committed,sent['execution'])
        return await await_callback_result(self.ctx.get('agents').withoutInitiator(lambda:self.transact(work)))

    runNow=run_now
    def is_execution_active(self,id):return id in self.executing
    isExecutionActive=is_execution_active
    def delivery_floor_end(self,task):
        end=self.next_admission_at(task)
        return end if end>now_ms() else None
    deliveryFloorEnd=delivery_floor_end

    async def drive(self):
        self.clear_timer();failed=set();handled=set();scan_now=now_ms()
        due=[task for task in self.tasks() if task['status']=='active' and task['record']['id'] not in self.executing and epoch(task['record']['scheduledAt'])<=scan_now]
        for task in due:
            if self.stopping:return
            if task['record']['id'] in handled:continue
            session=batch_session_of(task)
            group=[task] if session is None else [candidate for candidate in due if batch_session_of(candidate)==session]
            handled.update(member['record']['id'] for member in group)
            failed.update(await self.deliver_due(group,session is not None))
        if self.stopping:return
        obligations=[max(epoch(task['record']['scheduledAt']),self.next_admission_at(task)) for task in self.tasks()
            if task['status']=='active' and task['record']['id'] not in failed and task['record']['id'] not in self.executing]
        if obligations:
            delay=max(0,min(min(obligations)-now_ms(),MAX_TIMER_DELAY_MS))
            def fire():self.timer=None;self.request_drive()
            self.timer=asyncio.get_running_loop().call_later(delay/1000,fire)

    async def deliver_due(self,group,batch):
        admitted=group;committed=set()
        try:
            candidates=[]
            for member in group:
                if self.next_admission_at(member)>now_ms() or await self.recover_outstanding_execution(member):continue
                candidates.append(member)
            checked_at=now_ms();admitted=[member for member in candidates if epoch(member['record']['scheduledAt'])<=checked_at]
            if not admitted:return []
            target=await self.resolve_target(admitted[0])
            if self.stopping:return []
            now=now_ms();admitted=[member for member in admitted if epoch(member['record']['scheduledAt'])<=now]
            deliveries=[dict(task=task,occurrence=resolve_recurring_occurrence(task['record'],now) if is_recurring_schedule_record(task['record']) else dict(occurrenceAt=task['record']['scheduledAt'])) for task in admitted]
            if not deliveries:return []
            first=deliveries[0]
            text=(render_recurring_reminder_batch_framing([dict(record=item['task']['record'],occurrenceAt=item['occurrence']['occurrenceAt']) for item in deliveries])
                if batch else render_reminder_framing(dict(first['task']['record'],scheduledAt=first['occurrence']['occurrenceAt'])))
            held=[item['task']['record']['id'] for item in deliveries if item['task']['target']['kind']!='new']
            sent=await self.send(target['agent'],text,held)
            try:
                for item in deliveries:
                    receipt=dict(scheduledAt=item['occurrence']['occurrenceAt'],deliveredAt=sent['deliveredAt'],messageId=sent['messageId'],targetSessionId=target['sessionId'])
                    await await_callback_result(self.commit(self.advanced(item['task'],item['occurrence'],receipt)))
                    committed.add(item['task']['record']['id'])
            finally:self.settle(held,committed,sent['execution'])
            return []
        except Exception as error:
            pending=[member for member in admitted if member['record']['id'] not in committed];failed_at=now_ms()
            self.ctx.logger.warn('schedule: reminders '+stringify_json([member['record']['id'] for member in pending])+' were not acknowledged: '+_js_error_to_string(error))
            return [member['record']['id'] for member in pending if epoch(member['record']['scheduledAt'])<=failed_at]

    def next_admission_at(self,task):
        receipt=task.get('lastDelivery')
        if receipt is None:return float('-inf')
        interval=self.limits['newSessionIntervalMs'] if task['target']['kind']=='new' else MIN_DELIVERY_INTERVAL_MS
        occurrence=epoch(receipt['scheduledAt'])
        anchor=occurrence if epoch(task['record']['scheduledAt'])-occurrence>=interval else epoch(receipt['deliveredAt'])
        return anchor+interval

    def archived(self,id):return id in field(self.ctx.get('workspaceRegistry'),'archivedSessionIds',[])

    async def recover_outstanding_execution(self,task):
        id=task['record']['id']
        if id in self.executing:return True
        receipt=task.get('lastDelivery')
        if receipt is None or self.archived(receipt['targetSessionId']):return False
        try:agent=await self.activate(receipt['targetSessionId'])
        except Exception as error:
            self.ctx.logger.warn('schedule: could not restore the last delivery\'s Session for task "'+id+'": '+_js_error_to_string(error));return False
        message=next((message for message in list(agent.inbox.nextTurn)+list(agent.inbox.nextStep) if message['id']==receipt['messageId']),None)
        if message is None:return False
        held=[candidate['record']['id'] for candidate in self.tasks() if candidate['target']['kind']!='new'
            and candidate.get('lastDelivery',{}).get('messageId')==receipt['messageId'] and candidate['lastDelivery']['targetSessionId']==receipt['targetSessionId']]
        self.executing.update(held)
        try:
            if agent.status=='idle':
                agent.inbox.remove(message['id']);agent.followup(message)
                execution=observed_future(agent.whenIdle()) if held else None
                flushed=await await_callback_result(self.ctx.get('sessions').flush(agent.session))
                if not flushed:raise RuntimeError('Session persistence did not acknowledge the recovered reminder')
                if execution is not None:self.watch_execution(held,execution)
            elif held:self.watch_execution(held,observed_future(agent.whenIdle()))
            return id in held
        except Exception:
            self.executing.difference_update(held);raise

    async def send(self,agent,text,held):
        message=create_user_message(dict(content=[dict(type='text',text=text)],source=dict(kind='schedule')))
        self.executing.update(held)
        try:
            agent.followup(message)
            execution=observed_future(agent.whenIdle()) if held else None
            flushed=await await_callback_result(self.ctx.get('sessions').flush(agent.session))
            if not flushed:raise RuntimeError('Session persistence did not acknowledge the reminder')
            return dict(messageId=message['id'],deliveredAt=iso(now_ms()),execution=execution)
        except Exception:
            self.executing.difference_update(held);raise

    def settle(self,held,committed,execution):
        self.executing.difference_update(id for id in held if id not in committed)
        watched=[id for id in held if id in committed]
        if watched and execution is not None:self.watch_execution(watched,execution)

    def watch_execution(self,ids,execution):
        def finish(done):
            if not done.cancelled():done.exception()
            self.executing.difference_update(ids)
            if self.stopping:return
            self.changed();self.request_drive()
        execution.add_done_callback(finish)

    def delivered(self,task,receipt):
        result=dict(task,target=dict(kind='session',sessionId=receipt['targetSessionId']) if task['target']['kind']=='new_once' else task['target'],
            involvedSessionIds=task['involvedSessionIds'] if task['target']['kind']=='new' else list(dict.fromkeys(task['involvedSessionIds']+[receipt['targetSessionId']])),
            updatedAt=iso(max(epoch(receipt['deliveredAt']),epoch(task['updatedAt'])+1 if 'updatedAt' in task else epoch(receipt['deliveredAt']))),
            **append_delivery(task,receipt,self.limits['retention']))
        result.pop('pendingDelivery',None)
        return result

    def advanced(self,task,occurrence,receipt):
        return dict(self.delivered(task,receipt),record=dict(task['record'],scheduledAt=occurrence.get('nextScheduledAt',occurrence['occurrenceAt'])),
            status='ended' if 'nextScheduledAt' not in occurrence else 'active')

    async def resolve_target(self,task):
        target=task['target'];reserved=task.get('pendingDelivery',{}).get('targetSessionId') if target['kind']=='new' else target['sessionId']
        if reserved is not None and self.archived(reserved):raise RemoteError('schedule/target-archived','Session '+reserved+' is archived',dict(sessionId=reserved))
        if target['kind']=='session':return dict(sessionId=target['sessionId'],agent=await self.activate(target['sessionId']))
        agent=None
        if target['kind']=='new_once':id=target['sessionId'];agent=await self.reserved_agent(id)
        elif 'pendingDelivery' not in task:
            id='session-'+str(uuid.uuid4());await await_callback_result(self.commit(dict(task,pendingDelivery=dict(targetSessionId=id))))
        else:id=task['pendingDelivery']['targetSessionId'];agent=await self.reserved_agent(id)
        if agent is None:agent=await self.create_agent(id,target['create'])
        await self.join_workspace(id,target['create'].get('cwd'));self.name_session(agent,task)
        return dict(sessionId=id,agent=agent)

    async def reserved_agent(self,id):
        try:return await self.activate(id)
        except Exception as error:
            if isinstance(error,SessionPersistenceNotFoundError) or isinstance(error,RemoteError) and error.code=='session/not-found':return None
            raise

    async def activate(self,id):
        return await await_callback_result(self.ctx.waterfall('schedule/resolve-agent',id,lambda:self.resolve_agent(id)))

    async def create_agent(self,id,create):
        controller=self.ctx.get('sessionController')
        if controller is None:raise RuntimeError('schedule: no Session creation provider')
        await await_callback_result(controller.create(dict(sessionId=id,**create)))
        return await self.activate(id)

    async def join_workspace(self,id,cwd):
        registry=self.ctx.get('workspaceRegistry')
        if registry is None or cwd is None:return
        try:
            workspace=await await_callback_result(registry.resolveByPath(cwd))
            if workspace is not None:await await_callback_result(workspace.attachSession(id))
        except Exception as error:self.ctx.logger.warn('schedule: Session '+id+' did not join the Workspace at '+cwd+': '+_js_error_to_string(error))

    def name_session(self,agent,task):
        titles=self.ctx.get('sessionTitle')
        if titles is None or titles.get(agent.session) is not None:return
        try:
            title=task['record']['title']
            if task['target']['kind']=='new':title+=' · '+format_schedule_local_time(task['record'],iso(now_ms()))[:16].replace('T',' ')
            titles.rename(agent.session,title)
        except Exception as error:self.ctx.logger.warn('schedule: Session '+agent.id+' was not named: '+_js_error_to_string(error))


ScheduleRuntime=CurrentScheduleRuntime
