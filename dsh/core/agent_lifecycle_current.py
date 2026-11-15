"""Candidate Agent write ownership and publication against v3 handles.

The request driver migrates separately; no active profile mounts this service yet.
"""
import asyncio
import copy
import inspect
import uuid

from dsh.cordis.errors import AggregateError
from dsh.cordis.awaiting import resume_coroutine
from dsh.core.agent_factory import FactoryTransaction
from dsh.core.agent_loop import AgentLoopService, AgentLoopPlugin
from dsh.core.configured_agents import ConfiguredStartup
from dsh.core.session.json import UNDEFINED
from dsh.core.session.preparation import SessionPreparation
from dsh.core.session.repair import interruptedTurnClosers
from dsh.session.persistence import SessionPersistenceNotFoundError


class CurrentFactoryTransaction(FactoryTransaction):
    def __init__(self,*args,**kwargs):
        self.stored=None
        self.ready=False
        self.publication=None
        super().__init__(*args,**kwargs)
        self.format_version=getattr(self.factory._runtime['ctx'].get('agents'),'format_version',3)
        signal=args[3] if len(args)>3 else kwargs.get('signal')
        self.caller_remove=self.listeners[0] if signal is not None else None

    def mark_ready(self):
        self.ready=True
        if self.caller_remove is not None:
            self.caller_remove()
            if self.caller_remove in self.listeners:self.listeners.remove(self.caller_remove)
            self.caller_remove=None

    def dispose(self, owner_triggered=False):
        if self.disposing is None:
            self.controller.abort(RuntimeError('agent "%s" disposed' % self.sid))
            completion = self.disposing = asyncio.get_running_loop().create_future()
            operation = self._dispose(owner_triggered)
            # JS async disposal cancels the machine before yielding to owner
            # cleanup. Enter that prefix before the composite drops its scope.
            try:
                awaited = operation.send(None)
            except StopIteration as stop:
                completion.set_result(stop.value)
            except BaseException as error:
                completion.set_exception(error)
            else:
                task = asyncio.create_task(resume_coroutine(operation, awaited))
                def settled(job):
                    if job.cancelled():completion.cancel()
                    elif job.exception() is not None:completion.set_exception(job.exception())
                    else:completion.set_result(job.result())
                task.add_done_callback(settled)
        async def observe():
            return await asyncio.shield(self.disposing)
        return observe()

    async def _dispose(self,owner_triggered):
        failures=[]
        for remove in self.listeners:remove()
        self.listeners.clear()
        try:
            try:
                if self.format_version == 4 and self.publication is not None:
                    await asyncio.shield(self.publication)
                if self.agent is not None:
                    if self.format_version == 4:
                        try:self.agent.cancel(dict(kind='disposed'),dict(keepInbox=not self.ready))
                        except BaseException as error:failures.append(error)
                    else:self.agent.cancel(dict(kind='disposed'))
                    await self.agent.when_idle()
                if self.driver is not None:
                    self.driver.cancel()
                    await asyncio.gather(self.driver,return_exceptions=True)
                    if self.driver in self.factory._active_tasks:self.factory._active_tasks.remove(self.driver)
                if self.scope is not None:await self.scope.dispose()
            except BaseException as error:failures.append(error)
            try:
                # Python continuations can still own the final turn's flush
                # after machine idle. Join that session's admitted cache cuts
                # before closing its writer; unrelated sessions remain free.
                cache = self.factory.ctx.get('sessionProjectionCache')
                if cache is not None and self.agent is not None:
                    await cache.drain(self.agent.session)
                if self.stored is not None:await self.stored['handle'].close()
            except BaseException as error:failures.append(error)
            for detach in (self.detach_agent,self.detach_session):
                try:
                    if detach is not None:detach()
                except BaseException as error:failures.append(error)
        finally:
            self.factory._transactions.discard(self)
            if not owner_triggered and self.unfollow is not None:
                try:
                    result=self.unfollow()
                    if inspect.isawaitable(result):await result
                except BaseException as error:failures.append(error)
        if len(failures)==1:raise failures[0]
        if failures:raise AggregateError(failures,'agent "%s" disposal failed' % self.sid)


class CurrentConfiguredStartup(ConfiguredStartup):
    async def restore(self,row,options,meta,persistence,explicit=False):
        sid=row['resumeSessionId'] if explicit else row['sessionId']
        try:
            if not explicit:await self.wait_released(sid)
            if not self.active():return
            try:
                await self.factory.resume(sid,options,owner_ctx=self.ctx,persistence=persistence)
                return
            except Exception as error:
                if not self.active():return
                if explicit or not isinstance(error,SessionPersistenceNotFoundError):raise
            if self.active():await self.factory.create_agent(sid,options,meta,owner_ctx=self.ctx)
        except Exception as error:self.report(row['id'],'resume' if explicit else 'restore',sid,error)


class CurrentAgentLifecycleService(AgentLoopService):
    def __init__(self,ctx,config=None):
        super().__init__(ctx,config)
        # Like Source's runtime holder, keep the factory's dependency context
        # outside Cordis caller tracing. A registry caller must not own the
        # machine scope that the factory must drain during dependency loss.
        self._runtime = dict(ctx=ctx)
        self._configured=CurrentConfiguredStartup(self)

    async def _before_publish(self,tx,session):
        await self.appendUnstoredSuffix(tx.stored,session)

    def _invoke_setup(self,setup,agent):
        from dsh.cordis.utils import _js_call_callback
        return _js_call_callback(setup,(agent.ctx,agent))

    async def createStoredSession(self,session,signal=None):
        persistence=self.ctx.get('sessionPersistence')
        if persistence is None:return None
        options=dict(inheritedEventCount=session.inheritedEventCount)
        if signal is not None:options['signal']=signal
        return dict(handle=await persistence.create(session.header,options),storedCount=0)

    async def appendUnstoredSuffix(self,stored,session):
        if stored is None:return
        suffix=session.snapshotEvents(stored['storedCount'])
        if suffix:await stored['handle'].append(suffix)
        stored['storedCount']+=len(suffix)

    @staticmethod
    def _validate_options(options):
        maximum=getattr(options,'max_tokens',None)
        if maximum is not None and (type(maximum) not in (int,float) or not 1<=maximum<=9007199254740991 or int(maximum)!=maximum):
            raise TypeError('agent maxTokens must be a positive safe integer')

    async def _rollback(self,tx):
        try:await tx.dispose()
        except BaseException:pass

    async def create_agent(self,session_id=None,options=None,meta=None,setup=None,seed=None,signal=None,
                           owner_ctx=None,inherited_event_count=UNDEFINED,parent_agent=None):
        sid=session_id if session_id is not None else 'session-'+uuid.uuid4().hex[:8]
        sessions = self._runtime['ctx'].sessions
        tx=CurrentFactoryTransaction(self,owner_ctx or self.ctx,sid,signal)
        tx.parent_agent=parent_agent
        wrapper=asyncio.get_running_loop().create_future();self._wrappers.add(wrapper)
        preparation=None
        try:
            preparation=SessionPreparation.create(sessions.prepare(sid,
                seed=seed,meta=meta,inheritedEventCount=inherited_event_count))
            tx.stored=await tx.race(lambda:self.createStoredSession(preparation.session,signal),
                                   lambda late:None if late is None else late['handle'].close())
            self._validate_options(options)
            return await self._publish_preparation(tx,preparation,options,setup,'startup')
        except BaseException:
            await self._rollback(tx)
            raise
        finally:
            if preparation is not None:preparation.dispose()
            self._wrappers.discard(wrapper)
            if not wrapper.done():wrapper.set_result(None)
    create=create_agent

    async def resume(self,resume_session_id,options=None,setup=None,signal=None,owner_ctx=None,persistence=None,parent_agent=None):
        sid=resume_session_id
        persistence=persistence if persistence is not None else self.ctx.get('sessionPersistence')
        if persistence is None:
            raise RuntimeError('cannot resume: session persistence is not configured (load a dsh-session-persistence backend)')
        tx=CurrentFactoryTransaction(self,owner_ctx or self.ctx,sid,signal)
        tx.parent_agent=parent_agent
        wrapper=asyncio.get_running_loop().create_future();self._wrappers.add(wrapper)
        preparation=None
        try:
            handle=await tx.race(lambda:persistence.open(sid,'write',dict(signal=tx.controller.signal)),lambda late:late.close())
            tx.stored=dict(handle=handle,storedCount=0)
            read=await tx.race(lambda:handle.read(options=dict(signal=tx.controller.signal)))
            persisted=read['events'];closers=interruptedTurnClosers(persisted,format_version=getattr(self.ctx.get('sessions'),'format_version',3))
            if closers:await handle.append(closers)
            preparation=SessionPreparation.create(self.ctx.get('sessions').prepare(sid,
                seed=list(persisted)+closers,meta=copy.deepcopy(handle.header),inheritedEventCount=handle.inheritedEventCount,
                eventState=read['eventState']))
            tx.stored['storedCount']=len(persisted)+len(closers)
            await self.appendUnstoredSuffix(tx.stored,preparation.session)
            tx.assert_live();self._validate_options(options)
            return await self._publish_preparation(tx,preparation,options,setup,'resume')
        except BaseException:
            await self._rollback(tx)
            raise
        finally:
            if preparation is not None:preparation.dispose()
            self._wrappers.discard(wrapper)
            if not wrapper.done():wrapper.set_result(None)


class CurrentAgentLifecyclePlugin(AgentLoopPlugin):
    _service_class=CurrentAgentLifecycleService
