"""rc.3 process-local continuable residency and child-first release."""
import asyncio
import weakref
from types import SimpleNamespace

from dsh.cordis.errors import AggregateError
from dsh.core.react_loop_current import ReactLoopAgent
from dsh.llm.error import error_chain
from dsh.subagent.continuation import ActivationOwner
from dsh.subagent.composition import append_policy
from dsh.subagent.composition_current import apply_child_composition
from dsh.subagent.inbox_current import SubagentInbox
from dsh.subagent.continuation_messages_current import createSettlementMessage
from dsh.subagent.errors import SubagentError
from dsh.subagent.activation import ChildLock


def failure(message,cause=None):
    error=SubagentError(message,'ACTIVATION_TEARDOWN_FAILED')
    if cause is not None:error.cause=cause
    return error


class ContinuableActivationRegistry:
    def __init__(self,ctx,observe):
        self.ctx,self.observe=ctx,observe;self.resident={};self.materializations={};self.closing_scopes={};self.draining=False
        self.locks=ChildLock();scope=ctx.plugin(ActivationOwner);self.owner_ctx=scope.ctx;self.watchers=set()
        ctx.on('agent/disposed',lambda payload:self.closing_scopes.pop(payload['agent'],None))
        def effects():
            yield scope.dispose
            yield self.drain
        ctx.effect(effects,'subagents.continuations()')

    def lineage(self,agent):
        result=[];seen=set()
        while agent is not None and agent.id not in seen:
            result.append(agent);seen.add(agent.id);sid=agent.session.header.parentSession
            agent=self.ctx.get('agents').get(sid) if sid is not None else None
        return result

    def closing_for(self,agent):
        if self.draining:return 'manager'
        lineage=self.lineage(agent)
        for root,members in self.closing_scopes.items():
            if agent in members or root in lineage:return root
        return None

    def admitting(self,agent):
        closing=self.closing_for(agent)
        if closing is not None:
            raise SubagentError('continuable subagents are draining; the operation was not admitted' if closing=='manager'
                else 'continuable subagents below parent "%s" are draining; the operation was not admitted' % closing.id,'DRAINING')

    def available(self,sid):
        sessions=self.ctx.get('sessions')
        if self.ctx.get('agents').get(sid) is not None or sessions is not None and sessions.get(sid) is not None:
            raise SubagentError('subagent "%s" already exists' % sid,'DUPLICATE_CHILD')

    def authorize(self,parent,sid,parent_id):
        if self.ctx.get('agents').get(parent.id) is not parent:
            raise SubagentError('subagent "%s" delivery requires the exact live parent agent' % sid,'UNAUTHORIZED')
        if parent_id!=parent.id:raise SubagentError('subagent "%s" belongs to another parent session' % sid,'UNAUTHORIZED')

    def acquire(self,parent,sid):
        owner=self.resident.get(parent.id)
        if owner is not None:
            if owner.inbox.closing is not None:
                raise SubagentError('subagent parent "%s" is being disposed; the child was not established' % parent.id,'ACTIVATION_CLOSING')
            owner.children.add(sid)

    def hold_ownership(self,parent,sid):
        owner=self.resident.get(parent.id)
        if owner is None or owner.handle.agent is not parent:return lambda:None
        if owner.inbox.closing is None and sid in owner.children:return lambda:None
        self.acquire(parent,sid)
        def release():
            live=self.resident.get(sid)
            if live is not None and live.inbox.closing is None:return
            if sid in owner.children:owner.children.remove(sid);self.wake(owner)
        # An existing ownership edge belongs to its earlier operation.
        # acquire is idempotent, but the failure releaser must not remove that edge.
        return release

    def release_ownership(self,sid):
        for owner in self.resident.values():
            if sid in owner.children:owner.children.remove(sid);self.wake(owner)

    @staticmethod
    def wake(a):
        if not a.poke.done():a.poke.set_result(None)
        a.poke=asyncio.get_event_loop().create_future()

    def send_waking(self,parent,message,delivery):
        owner=self.resident.get(parent.id)
        if owner is not None and owner.handle.agent is parent:
            try:owner.inbox.deliver(message,delivery)
            finally:self.wake(owner)
        else:(parent.steer if delivery=='steer' else parent.followup)(message)

    def submit(self,a,message,delivery,parent,signal):
        signal.throwIfAborted();self.admitting(parent)
        self.authorize(parent,a.id,a.handle.agent.session.header.parentSession);self.acquire(parent,a.id)
        try:a.inbox.deliver(message,delivery)
        finally:self.wake(a)
        return message['id']

    async def materialize(self,sid,provider,parent,options,composition,signal,create=None):
        self.admitting(parent);lineage=self.lineage(parent);barrier=asyncio.get_event_loop().create_future()
        self.materializations[barrier]=lineage
        try:
            signal.throwIfAborted()
            def setup(child_ctx,child):
                if create is not None:
                    child.session.append('subagent/descriptor',create['descriptor']);append_policy(child.session,create['policy'])
                apply_child_composition(child_ctx,parent,composition)
            observer=self.observe(provider,sid,parent)
            args=dict(parentAgent=parent,agentOptions=options,signal=signal,setup=setup)
            if create is None:handle=await self.owner_ctx.get('agents').resume(dict(args,resumeSessionId=sid))
            else:
                args.update(sessionId=sid,meta=create['meta'],inheritedEventCount=create['inheritedEventCount'])
                if create.get('seed') is not None:args['seed']=create['seed']
                handle=await self.owner_ctx.get('agents').create(args)
            a=SimpleNamespace(id=sid,parent=parent.id,provider=provider,handle=handle,inbox=SubagentInbox(handle.agent),
                ancestry=weakref.WeakSet([handle.agent]+lineage),children=set(),observer=observer,announced=False,
                poke=asyncio.get_event_loop().create_future())
            self.resident[sid]=a
            try:
                signal.throwIfAborted();self.admitting(parent);self.acquire(parent,sid)
                handle.agent.ctx.on('agent/inbox/claimed',lambda payload:self.wake(a))
                handle.agent.ctx.on('agent/inbox/discarded',lambda payload:self.wake(a))
                observer.start(handle.agent)
            except BaseException:
                async def rollback():
                    try:await handle.dispose()
                    finally:self.resident.pop(sid,None);self.release_ownership(sid)
                await asyncio.gather(asyncio.shield(a.inbox.close(rollback)),return_exceptions=True)
                raise
            watcher=asyncio.create_task(self.watch(a));self.watchers.add(watcher)
            def settled(task):
                self.watchers.discard(task)
                if not task.cancelled() and task.exception() is not None:self.ctx.logger.warn('subagent watcher failed: '+error_chain(task.exception()))
            watcher.add_done_callback(settled)
            return a
        finally:self.materializations.pop(barrier,None);barrier.set_result(None)

    @staticmethod
    def state(a,observation):
        if a.inbox.closing is not None:return 'closed'
        if a.poke is not observation:return 'retry'
        if a.inbox.hasPending or a.children:return 'wait'
        return 'ready'

    async def flush(self,a):
        try:await a.handle.agent.ctx.get('sessions').flush(a.handle.agent.session)
        except Exception as error:self.ctx.logger.warn('subagent "%s" best-effort final session flush failed: %s' % (a.id,error_chain(error)))

    async def watch(self,a):
        while True:
            observation=a.poke;await a.handle.agent.whenIdle()
            if a.inbox.closing is not None:return
            async with self.locks.hold(a.id):ready=self.state(a,observation)
            if ready=='closed':return
            if ready=='retry':continue
            if ready=='wait':await asyncio.shield(observation);continue
            seq=a.handle.agent.session.seq;await self.flush(a)
            done=None
            async with self.locks.hold(a.id):
                ready=self.state(a,observation)
                if ready=='ready' and a.handle.agent.session.seq!=seq:ready='retry'
                if ready=='ready':
                    def reserve(signal):
                        nonlocal done
                        done=self.dispose(a,True)
                    try:a.handle.agent.runMaintenance(reserve)
                    except Exception:ready='retry'
            if ready=='closed':return
            if ready=='retry':continue
            if ready=='wait':await asyncio.shield(observation);continue
            try:await asyncio.shield(done)
            except Exception as error:self.ctx.logger.warn('subagent "%s" activation teardown failed: %s' % (a.id,error_chain(error)))
            return

    def dispose(self,a,flushed=False):return a.inbox.close(lambda:self.finish_disposal(a,flushed))

    async def finish_disposal(self,a,flushed):
        self.wake(a);failures=[]
        if not flushed:
            a.handle.agent.cancel(dict(kind='parent'))
            idle=ReactLoopAgent._start(a.handle.agent.whenIdle())
            children=[self.dispose(self.resident[sid]) for sid in list(a.children) if sid in self.resident]
            outcomes=await asyncio.gather(*children,return_exceptions=True)
            reasons=[e for e in outcomes if isinstance(e,BaseException)]
            if reasons:failures.append(failure('subagent "%s" child teardown failed: %s' % (a.id,'; '.join(error_chain(e) for e in reasons))))
            try:await idle;await self.flush(a);a.observer.capture(a.handle.agent)
            except BaseException as error:failures.append(failure('subagent "%s" activation teardown failed: %s' % (a.id,error_chain(error)),error))
        else:
            try:a.observer.capture(a.handle.agent)
            except BaseException as error:failures.append(failure('subagent "%s" activation teardown failed: %s' % (a.id,error_chain(error)),error))
        try:await a.handle.dispose()
        except BaseException as error:failures.append(failure('subagent "%s" activation handle disposal failed: %s' % (a.id,error_chain(error)),error))
        error=failures[0] if len(failures)==1 else failure('subagent "%s" activation teardown failed at %s boundaries: %s' % (a.id,len(failures),'; '.join(error_chain(e) for e in failures)),AggregateError(failures)) if failures else None
        self.resident.pop(a.id,None);self.notify(a,a.observer.terminal(error));self.release_ownership(a.id);a.observer.settle(error)
        if error is not None:raise error

    def notify(self,a,terminal):
        if not a.announced:return
        try:
            parent=self.ctx.get('agents').get(a.parent)
            if parent is None:return
            message=createSettlementMessage(a.id,terminal)
            if self.closing_for(parent) is not None:parent.inject(message)
            else:self.send_waking(parent,message,'queue' if parent.status=='idle' else 'steer')
        except Exception as error:self.ctx.logger.warn('subagent "%s" settlement notice was not delivered: %s' % (a.id,error_chain(error)))

    async def dispose_roots(self,roots,subject='activation(s)'):
        results=await asyncio.gather(*(self.dispose(a) for a in roots),return_exceptions=True)
        errors=[e for e in results if isinstance(e,BaseException)]
        if errors:raise failure('continuable subagent teardown failed for %s %s: %s' % (len(errors),subject,'; '.join(error_chain(e) for e in errors)))

    async def drain(self):
        self.draining=True
        await asyncio.gather(*(asyncio.shield(p) for p in list(self.materializations)))
        owned={sid for a in self.resident.values() for sid in a.children}
        await self.dispose_roots([a for a in self.resident.values() if a.id not in owned])

    async def drain_descendants(self,parents):
        roots=[p for p in parents if self.ctx.get('agents').get(p.id) is p]
        if not roots:return
        for root in roots:self.closing_scopes.setdefault(root,set()).add(root)
        targets=[];barriers=[]
        for a in self.resident.values():
            owners=[root for root in roots if a.handle.agent is not root and root in a.ancestry]
            if not owners:continue
            targets.append(a)
            for root in owners:self.closing_scopes[root].update(self.lineage(a.handle.agent))
        for barrier,lineage in self.materializations.items():
            owners=[root for root in roots if root in lineage]
            if owners:barriers.append(barrier)
            for root in owners:self.closing_scopes[root].update(lineage)
        owned={sid for a in targets for sid in a.children};target_roots=[a for a in targets if a.id not in owned]
        for a in targets:self.dispose(a)
        await asyncio.gather(*(asyncio.shield(p) for p in barriers))
        await self.dispose_roots(target_roots,'scoped activation(s)')

    async def drain_children(self,parent,ids):
        if self.ctx.get('agents').get(parent.id) is not parent:raise SubagentError('selected child teardown requires the exact live parent agent','UNAUTHORIZED')
        targets=[]
        for sid in dict.fromkeys(ids):
            a=self.resident.get(sid)
            if a is None:continue
            if a.parent!=parent.id or parent not in a.ancestry:raise SubagentError('subagent "%s" is not a direct child of agent "%s"' % (sid,parent.id),'UNAUTHORIZED')
            targets.append(a)
        for a in targets:self.dispose(a)
        await self.dispose_roots(targets,'selected activation(s)')

    def interrupt(self,sid,authority):
        ancestor=authority.get('agent')
        if authority['kind']=='ancestor':
            if self.ctx.get('agents').get(ancestor.id) is not ancestor:raise SubagentError('interrupting "%s" requires the exact live ancestor agent' % sid,'UNAUTHORIZED')
            if ancestor.id==sid:raise SubagentError('agent "%s" cannot interrupt itself' % ancestor.id,'UNAUTHORIZED')
        a=self.resident.get(sid)
        if a is None:return
        if authority['kind']=='user':
            if a.handle.agent.session.header.parentSession!=authority['parentSessionId']:raise SubagentError('subagent "%s" belongs to another parent session' % sid,'UNAUTHORIZED')
        elif ancestor not in a.ancestry:raise SubagentError('subagent "%s" is not a live descendant of agent "%s"' % (sid,ancestor.id),'UNAUTHORIZED')
        if a.inbox.closing is None:a.handle.agent.cancel(dict(kind='user' if authority['kind']=='user' else 'parent'),dict(keepInbox=True))
