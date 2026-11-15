"""Input waits leave the inbox intact and release every listener/timer."""
import asyncio
import weakref
from dsh.core.abort import AbortController,abort_reason_error
from dsh.llm.error import HarnessError
from dsh.subagent.projections import integer


class AgentWaitError(HarnessError):
    pass


class InputWaits:
    def __init__(self,ctx):
        self.ctx,self.lifetime,self.reported=ctx,AbortController(),weakref.WeakKeyDictionary()
        def unload():
            self.lifetime.abort(AgentWaitError('wait_agent ended because its plugin was unloaded','WAIT_UNAVAILABLE'))
        ctx.effect(lambda:unload,'subagent-control.waits()')

    async def execute(self,args,execution):
        timeout=30000 if args.get('timeout_ms') is None else args['timeout_ms']
        try:integer(timeout)
        except ValueError:timeout=-1
        if timeout<10000 or timeout>3600000:
            raise AgentWaitError('timeout_ms must be an integer from 10000 through 3600000','WAIT_INVALID_TIMEOUT')
        if execution.agent is None:
            raise AgentWaitError('wait_agent requires a calling agent','WAIT_UNAVAILABLE')
        return await self.wait_for_input(execution.agent,timeout,execution.signal,execution.rootCallId)

    async def wait_for_input(self,agent,timeout,signal,root_call_id):
        lifetime=self.lifetime.signal
        lifetime.throwIfAborted()
        if self.ctx.get('agents').get(agent.id) is not agent:
            raise AgentWaitError('wait_agent requires the exact live calling agent','WAIT_UNAVAILABLE')
        previous=self.reported.get(agent)
        seen=previous['ids'] if previous is not None and previous['rootCallId']==root_call_id else set()
        result=asyncio.get_running_loop().create_future()
        def cleanup():
            timer.cancel();off_inbox();off_disposed()
            signal.removeEventListener('abort',on_abort)
            lifetime.removeEventListener('abort',on_unload)
        def finish(value=None,error=None):
            cleanup()
            if result.done():return
            if error is not None:result.set_exception(error)
            else:result.set_result(value)
        def on_input():
            pending=agent.inbox.nextStep
            if any(message['id'] not in seen for message in pending):
                self.reported[agent]=dict(rootCallId=root_call_id,ids={message['id'] for message in pending})
                finish(dict(timedOut=False))
        def on_abort(*args):finish(error=abort_reason_error(signal))
        def on_unload(*args):finish(error=abort_reason_error(lifetime))
        def inbox(payload):
            if payload['agent'] is agent:on_input()
        def disposed(payload):
            if payload['agent'] is agent:
                finish(error=AgentWaitError('wait_agent ended because the calling agent was disposed','WAIT_UNAVAILABLE'))
        off_inbox=self.ctx.on('agent/inbox/inserted',inbox)
        off_disposed=self.ctx.on('agent/disposed',disposed)
        signal.addEventListener('abort',on_abort,dict(once=True))
        lifetime.addEventListener('abort',on_unload,dict(once=True))
        timer=asyncio.get_running_loop().call_later(timeout/1000,lambda:finish(dict(timedOut=True)))
        if signal.aborted:on_abort()
        else:on_input()
        try:return await result
        finally:cleanup()
