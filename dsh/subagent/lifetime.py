"""Execution ownership shared by local residency and external subagent runs."""
import asyncio
import weakref

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.cordis.errors import AggregateError
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.llm.error import error_chain
from dsh.subagent.activation import ActivationPool, ChildLock, capture_local_result, require_local_activation
from dsh.subagent.errors import SubagentError
from dsh.subagent.messages import create_settlement_message
from dsh.subagent.names import agent_address
from dsh.subagent.tree import SubagentTree, activation_agent


def future():
    return asyncio.get_running_loop().create_future()


def contain(task):
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return task


class ActivationOwner(Plugin):
    id = 'subagent-activation-owner-v4'
    def apply(self, ctx):
        pass


class SubagentLifetime(SubagentTree):
    def __init__(self, ctx, host, max_active_subagents):
        super().__init__(ctx,host)
        self.max_active_subagents = max_active_subagents
        self.root_pools = weakref.WeakKeyDictionary()
        self.materializations = set()
        self.locks = ChildLock()
        self.tasks = set()
        scope = ctx.plugin(ActivationOwner)
        self.owner_ctx = scope.ctx
        def disposed(payload):
            agent = payload['agent']
            self.closing_roots.discard(agent)
            activation = self.resident.get(agent.id)
            if activation is not None and activation.kind == 'local' and activation.handle.agent is agent:
                self.background(self.close(activation,lambda:self.finish_disposal(activation,False)),activation)
        ctx.on('agent/disposed',disposed)
        def effects():
            yield scope.dispose
            yield self.drain
        ctx.effect(effects,'subagents.manager()')

    def background(self, operation, activation=None):
        task = asyncio.ensure_future(operation)
        self.tasks.add(task)
        def completed(done):
            self.tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                if activation is not None:
                    self.report_teardown_failure(activation,error)
                else:
                    self.ctx.logger.warn('subagent background operation failed: '+str(error))
        task.add_done_callback(completed)
        return task

    def root_pool(self, root):
        pool = self.root_pools.get(root)
        if pool is None:
            pool = ActivationPool()
            self.root_pools[root] = pool
        return pool

    def track_startup(self, root, signal, start):
        self.assert_admitting(root)
        signal.throwIfAborted()
        controller, combined = AbortController(), AbortController()
        disposers = [subscribe_abort(source,lambda reason:combined.abort(reason)) for source in (signal,controller.signal)]
        class Materialization:
            pass
        pending = Materialization()
        pending.root,pending.controller,pending.settled = root,controller,future()
        self.materializations.add(pending)
        async def perform():
            try:
                return await await_callback_result(start(combined.signal))
            except Exception as error:
                if getattr(error,'name',None) == 'AbortError':
                    self.assert_admitting(root)
                raise
            finally:
                for dispose in disposers:
                    dispose()
                self.materializations.discard(pending)
                pending.settled.set_result(None)
        return start_coroutine(perform())

    def interrupt(self, target_id, authority):
        caller = authority.get('agent')
        if authority['kind'] == 'ancestor':
            if self.ctx.get('agents').get(caller.id) is not caller:
                raise SubagentError('interrupting "%s" requires the exact live ancestor agent' % target_id,'UNAUTHORIZED')
            if caller.id == target_id:
                raise SubagentError('agent "%s" cannot interrupt itself' % caller.id,'UNAUTHORIZED')
        activation = self.resident.get(target_id)
        if activation is None:
            return
        if authority['kind'] == 'ancestor' and (self.root_of(caller) is not activation.root or caller.id not in activation.ancestors):
            raise SubagentError('subagent "%s" is not a live descendant of agent "%s"' % (target_id,caller.id),'UNAUTHORIZED')
        if activation.closing is not None:
            return
        kind = 'user' if authority['kind'] == 'user' else 'parent'
        if activation.kind == 'local':
            activation.handle.agent.cancel(dict(kind=kind),dict(keepInbox=True))
        else:
            activation.controller.abort(dict(kind=kind))
            contain(self.dispose(activation))

    def close(self, activation, release):
        if activation.closing is not None:
            return activation.closing
        completion = future()
        activation.closing = completion
        async def perform():
            try:
                completion.set_result(await await_callback_result(release()))
            except BaseException as error:
                completion.set_exception(error)
        contain(start_coroutine(perform()))
        return completion

    def dispose(self, activation):
        return self.close(activation,lambda:self.finish_disposal(activation,True))

    async def dispose_roots(self, roots, subject):
        results = await asyncio.gather(*(asyncio.shield(self.dispose(item)) for item in roots),return_exceptions=True)
        failures = [item for item in results if isinstance(item,BaseException)]
        if failures:
            raise SubagentError('subagent teardown failed for %s %s: %s' %
                (len(failures),subject,'; '.join(str(item) for item in failures)),'ACTIVATION_TEARDOWN_FAILED')

    def drain(self):
        self.draining = True
        pending = list(self.materializations)
        for item in pending:
            item.controller.abort()
        async def perform():
            await asyncio.gather(*(asyncio.shield(item.settled) for item in pending))
            await self.dispose_roots(list(self.resident.values()),'activation(s)')
        return start_coroutine(perform())

    def drain_descendants(self, parents):
        agents = self.ctx.get('agents')
        roots = {root for root in parents if agents.get(root.id) is root and self.root_of(root) is root}
        self.closing_roots.update(roots)
        pending = [item for item in self.materializations if item.root in roots]
        for item in pending:
            item.controller.abort()
        targets = [item for item in self.resident.values() if item.root in roots]
        async def perform():
            results = await asyncio.gather(self.dispose_roots(targets,'scoped activation(s)'),
                *(asyncio.shield(item.settled) for item in pending),return_exceptions=True)
            if isinstance(results[0],BaseException):
                raise results[0]
        return start_coroutine(perform())

    async def wait_for_tree_work(self, root):
        if self.root_of(root) is not root:
            return False
        observed = False
        while True:
            pending = [item for item in self.materializations if item.root is root]
            children = [item for item in self.resident.values() if item.root is root]
            observed = observed or any(item.kind == 'local' and item.handle.agent.status != 'idle' for item in children)
            await asyncio.gather(*(item.handle.agent.whenIdle() for item in children if item.kind == 'local'))
            waits = [asyncio.shield(item.settled) for item in pending]
            for item in children:
                if item.kind == 'external' or item.closing is not None:
                    waits.append(self.ignore_result(item.result))
                elif item.handle.agent.status != 'idle':
                    waits.append(item.handle.agent.whenIdle())
                elif item.failureAt is None and (item.handle.agent.inbox.nextTurn or item.handle.agent.inbox.nextStep):
                    continue
                else:
                    waits.append(self.wait_either(item.result,item.poke))
            if waits:
                observed = True
                await asyncio.gather(*waits)
                continue
            if (any(item.root is root and item not in pending for item in self.materializations)
                    or any(item.root is root and item not in children for item in self.resident.values())):
                continue
            return observed

    @staticmethod
    async def ignore_result(result):
        await asyncio.gather(asyncio.shield(result),return_exceptions=True)

    @staticmethod
    async def wait_either(result, poke):
        waiting = [asyncio.shield(result),asyncio.shield(poke)]
        try:
            done,_ = await asyncio.wait(waiting,return_when=asyncio.FIRST_COMPLETED)
            for item in done:
                if not item.cancelled():
                    item.exception()
        finally:
            for item in waiting:
                if not item.done():
                    item.cancel()

    @staticmethod
    def wake(activation):
        if activation.kind != 'local':
            return
        if not activation.poke.done():
            activation.poke.set_result(None)
        activation.poke = future()

    def run_info(self, activation):
        return dict(runId=activation.runId,provider=activation.provider,parentSessionId=activation.ancestors[-1],
                    id=activation.childId,local=activation.kind == 'local')

    def accept(self, activation):
        activation.accepted = True
        if activation.kind == 'local':
            self.background(start_coroutine(self.watch_local_settlement(activation)),activation)
        else:
            async def settled():
                await self.ignore_result(activation.run.result)
                await asyncio.shield(self.close(activation,lambda:self.finish_disposal(activation,False)))
            self.background(start_coroutine(settled()),activation)

    async def rollback_unpublished(self, activation, error):
        async def release():
            try:
                await (activation.handle.dispose() if activation.kind == 'local' else activation.run.dispose())
            finally:
                self.resident.pop(activation.childId,None)
                activation.releaseSlot()
                activation.result.set_exception(error)
        await asyncio.shield(self.close(activation,release))

    @staticmethod
    def settlement_state(activation, observation):
        if activation.closing is not None:
            return 'closed'
        if activation.poke is not observation:
            return 'retry'
        inbox = activation.handle.agent.inbox
        if activation.failureAt is None and (inbox.nextTurn or inbox.nextStep):
            return 'wait'
        return 'ready'

    async def watch_local_settlement(self, activation):
        child = activation.handle.agent
        while True:
            observation = activation.poke
            await child.whenIdle()
            if activation.closing is not None:
                return
            async with self.locks.hold(activation.childId):
                readiness = self.settlement_state(activation,observation)
            if readiness == 'closed':
                return
            if readiness == 'retry':
                continue
            if readiness == 'wait':
                await asyncio.shield(observation)
                continue
            final_seq = child.session.seq
            await self.flush_final_state(activation)
            done = None
            async with self.locks.hold(activation.childId):
                state = self.settlement_state(activation,observation)
                if state == 'closed':
                    return
                if state != 'ready' or child.session.seq != final_seq:
                    continue
                def maintenance(_signal):
                    nonlocal done
                    done = self.close(activation,lambda:self.finish_disposal(activation,False))
                try:
                    contain(child.runMaintenance(maintenance))
                except Exception:
                    continue
            await asyncio.shield(done)
            return

    def report_teardown_failure(self, activation, error):
        self.ctx.logger.warn('subagent "%s" activation teardown failed: %s' % (activation.childId,error))

    async def finish_disposal(self, activation, stop):
        self.wake(activation)
        child_id, child = activation.childId,activation_agent(activation)
        failures, result = [],dict(output=[],stopReason='error')
        result_failure, external_disposal = None,None
        def detail(error):
            return str(error) if child is None else error_chain(error)
        def record(message, error):
            failure = SubagentError(message+detail(error),'ACTIVATION_TEARDOWN_FAILED')
            failure.cause = error
            failures.append(failure)
        try:
            if activation.kind == 'external':
                if stop:
                    activation.controller.abort(dict(kind='parent'))
                    async def external_release():
                        await asyncio.sleep(0)
                        return await activation.run.dispose()
                    external_disposal = contain(asyncio.create_task(external_release()))
                result = await asyncio.shield(activation.run.result)
            else:
                if stop:
                    child.cancel(dict(kind='parent'))
                    await child.whenIdle()
                    await self.flush_final_state(activation)
                result = capture_local_result(activation)
        except BaseException as error:
            result_failure = error
            record('subagent "%s" activation teardown failed: ' % child_id,error)
        try:
            if activation.kind == 'local':
                await activation.handle.dispose()
            elif external_disposal is not None:
                await asyncio.shield(external_disposal)
            else:
                await activation.run.dispose()
        except BaseException as error:
            record('subagent "%s" activation handle disposal failed: ' % child_id,error)
        failure = failures[0] if len(failures) == 1 else None
        if len(failures) > 1:
            failure = SubagentError('subagent "%s" activation teardown failed at %s boundaries: %s' %
                (child_id,len(failures),'; '.join(detail(item) for item in failures)),'ACTIVATION_TEARDOWN_FAILED')
            failure.cause = AggregateError(failures)
        if failure is not None and result['stopReason'] == 'completed' and child is not None and (child.inbox.nextStep or child.inbox.nextTurn):
            result = dict(result,stopReason='error')
        self.resident.pop(child_id,None)
        activation.releaseSlot()
        terminal = result if failure is None else dict(output=[],stopReason='error')
        self.notify_settlement(activation,result)
        info = dict(self.run_info(activation),stopReason=terminal['stopReason'])
        if terminal['output']:
            info['lastAssistantMessage'] = terminal['output']
        self.host.emitLifecycle('subagent/end',info,activation.root)
        if result_failure is None:
            activation.result.set_result(result)
        else:
            activation.result.set_exception(result_failure)
        if failure is not None:
            raise failure

    def send_waking(self, agent, message, delivery):
        activation = self.resident.get(agent.id)
        if activation is not None and activation_agent(activation) is agent:
            try:
                self.deliver(activation,message,delivery)
            finally:
                self.wake(activation)
            return
        (agent.steer if delivery == 'steer' else agent.followup)(message)

    @staticmethod
    def deliver(activation, message, delivery):
        if activation.closing is not None:
            raise SubagentError('subagent activation is being disposed; the message was not accepted','ACTIVATION_CLOSING')
        local = require_local_activation(activation)
        if local.structured is not None and local.structured.acceptsInput() is False:
            raise SubagentError('subagent is submitting or has submitted its structured result; the message was not accepted','INPUT_CLOSED')
        (local.handle.agent.steer if delivery == 'steer' else local.handle.agent.followup)(message)

    def notify_settlement(self, activation, terminal):
        if not activation.accepted or activation.delivery == 'caller':
            return
        try:
            parent = self.ctx.get('agents').get(activation.ancestors[-1])
            if parent is None or parent.ctx.fiber.state != FiberState.ACTIVE or self.root_of(parent) is not activation.root:
                return
            message = create_settlement_message(activation.childId,agent_address(activation.path,activation.childId),terminal,
                activation.kind == 'local',activation.kind == 'local' and activation.omitClosingText)
            if self.closing_teardown_for(parent) is not None:
                parent.inject(message)
            else:
                self.send_waking(parent,message,'queue' if parent.status == 'idle' else 'steer')
        except Exception as error:
            self.ctx.logger.warn('subagent "%s" settlement notice was not delivered to its parent: %s' %
                                 (activation.childId,error_chain(error)))

    async def flush_final_state(self, activation):
        try:
            child = activation.handle.agent
            await child.ctx.get('sessions').flush(child.session)
        except Exception as error:
            self.ctx.logger.warn('subagent "%s" best-effort final session flush failed; the persisted state may be '
                'unavailable or stale on resume: %s' % (activation.childId,error_chain(error)))

    def receipt(self, activation):
        return dict(childId=activation.childId,name=agent_address(activation.path,activation.childId),result=activation.result,
                    dispose=lambda:self.dispose(activation))

    waitForTreeWork = wait_for_tree_work
    drainDescendants = drain_descendants
