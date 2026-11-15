"""Contained run edges and suffix-bounded continuable epoch observations."""
import uuid

from dsh.core.agent_dispatch_current import AgentEventDispatch
from dsh.core.scope import scope_target
from dsh.cordis.utils import _js_call_callback
from dsh.core.consumed_work import fold_consumed_work
from dsh.subagent.assistant_output_current import final_assistant_output


class LifecycleEmitter:
    def __init__(self,ctx,service):
        self.ctx,self.service=ctx,service
        self.settler=AgentEventDispatch(ctx,None)

    def __call__(self,name,info,parent=None):
        args=[name,info] if parent is None else [scope_target(self.service,parent),name,info]
        for callback in self.ctx.events.dispatch('emit',args):
            try:self.settler._settle(_js_call_callback(callback,(info,),maximum=1),name)
            except BaseException as error:self.ctx.logger.warn('subagent: %s listener threw: %s' % (name,error))


def observe_run(emit,provider,parent,run):
    identity=dict(runId=str(uuid.uuid4()),provider=provider,id=run.id,parentSessionId=parent.session.id,local=getattr(run,'localAgent',None) is not None)
    def settled(future):
        info=dict(identity)
        try:
            result=future.result();info['stopReason']=result['stopReason']
            if result['output']:info['lastAssistantMessage']=result['output']
        except BaseException:info['stopReason']='error'
        emit('subagent/end',info,parent)
    run.result.add_done_callback(settled)
    emit('subagent/start',identity,parent)
    return run


class ActivationObserver:
    def __init__(self,emit,provider,child_id,parent):
        self.emit,self.parent=emit,parent
        self.identity=dict(runId=str(uuid.uuid4()),provider=provider,id=child_id,parentSessionId=parent.session.id,local=True)
        self.boundary=0;self.captured=dict(stopReason='completed')

    def start(self,child):
        self.boundary=child.session.seq
        self.emit('subagent/start',self.identity,self.parent)

    def capture(self,child):
        own=child.session.snapshotEvents(self.boundary);work=fold_consumed_work(own)
        kind=work.end['data']['reason']['kind'] if work.end is not None else None
        if kind in (None,'completed'):reason='aborted' if work.dropped_unrun else 'completed'
        else:reason={'max-tokens':'max-tokens','aborted':'aborted','interrupted':'aborted','error':'error','blocked':'refusal'}.get(kind,'error')
        self.captured=dict(stopReason=reason)
        output=final_assistant_output(own)
        if output is not None:self.captured['output']=output

    def terminal(self,failure=None):
        return self.captured if failure is None else dict(stopReason='error')

    def settle(self,failure=None):
        terminal=self.terminal(failure);info=dict(self.identity,stopReason=terminal['stopReason'])
        if 'output' in terminal:info['lastAssistantMessage']=terminal['output']
        self.emit('subagent/end',info,self.parent)
