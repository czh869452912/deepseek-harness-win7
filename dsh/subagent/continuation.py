"""Manager-owned background Agent epochs over durable child session identities."""
import asyncio
import logging
import uuid
import weakref
from types import SimpleNamespace

from dsh.cordis.plugin import Plugin
from dsh.core.agent import AgentOptions
from dsh.core.abort import NEVER_ABORTED
from dsh.core.session import Session
from dsh.core.notifications import emit_contained
from dsh.llm.message import create_user_message
from dsh.session.preparations import throw_aborted
from dsh.subagent.composition import child_depth, child_options, child_meta, capture_policy, append_policy, apply_composition
from dsh.subagent.descriptor import snapshot_descriptor, fold_descriptor
from dsh.subagent.errors import SubagentError
from dsh.subagent.in_process import read_result


class ActivationOwner(Plugin):
    id = 'subagent-activation-owner'

    def apply(self, ctx):
        pass


class ContinuationManager:
    def __init__(self, ctx, host, setups):
        self.ctx, self.host, self.setups = ctx, host, setups
        self.activations, self.locks, self.materializations = {}, {}, {}
        self.closing_scopes = weakref.WeakKeyDictionary()
        self.draining = False
        self.owner = ctx.plugin(ActivationOwner)
        self.owner_ctx = self.owner.ctx
        def effects():
            yield self.owner.dispose
            yield self.drain
        ctx.effect(effects, 'subagents.continuations()')
        ctx.on('agent/disposed', lambda payload: self.closing_scopes.pop(payload['agent'], None))

    def lock(self, sid):
        return self.locks.setdefault(sid, asyncio.Lock())

    def lineage(self, agent):
        lineage, seen = [], set()
        while agent is not None and agent not in seen:
            lineage.append(agent)
            seen.add(agent)
            parent_id = agent.session.header.parentSession
            agent = self.ctx.get('agents').get(parent_id) if parent_id else None
        return lineage

    def admitting(self, parent):
        lineage = self.lineage(parent)
        if self.draining or any(any(agent in members for agent in lineage) for members in self.closing_scopes.values()):
            raise SubagentError('subagent admission is closed', 'ACTIVATION_CLOSING')

    def authorize(self, parent, parent_id):
        if self.ctx.get('agents').get(parent.id) is not parent or parent.id != parent_id:
            raise SubagentError('operation requires the exact live direct parent', 'UNAUTHORIZED')

    def available(self, sid):
        if self.ctx.get('agents').get(sid) is not None or self.ctx.get('sessions').get(sid) is not None:
            raise SubagentError('subagent already exists: ' + sid, 'DUPLICATE_CHILD')

    def require(self, name):
        service = self.ctx.get(name)
        if service is None:
            raise SubagentError('continuable subagents require ' + name, 'NOT_RESUMABLE')
        return service

    async def start(self, spec):
        request, signal = spec['request'], spec.get('signal', NEVER_ABORTED)
        parent = request['parent']
        self.admitting(parent)
        persistence = self.require('sessionPersistence')
        sid = spec.get('childId', str(uuid.uuid4()))
        self.available(sid)
        depth = child_depth(parent, request.get('maxDepth'))
        options = child_options(parent, request.get('agentOptions'), depth)
        descriptor = dict(mode='continuable', provider=spec['provider'], label=spec['label'])
        for option, key in (('provider', 'agentProvider'), ('model', 'agentModel'), ('reasoningEffort', 'agentReasoningEffort')):
            value = getattr(options, option, None)
            if value is not None:
                descriptor[key] = value
        for key in ('persona', 'toolFilter'):
            if key in request:
                descriptor[key] = request[key]
        descriptor = snapshot_descriptor(descriptor)
        policy = capture_policy(parent)
        provider = self.host.expect_provider(spec['provider'])
        prepare = getattr(provider, 'prepareContinuable', None)
        if prepare is None:
            raise SubagentError('provider cannot prepare continuable children', 'UNSUPPORTED_CAPABILITY')
        throw_aborted(signal)
        prepared = await prepare(dict(sessionId=sid, parent=parent, signal=signal))
        throw_aborted(signal)
        self.admitting(parent)
        seed = prepared.get('seed', [])
        meta = child_meta(parent, depth, len(seed))
        staged = Session.create(sid, seed=seed)
        staged.append('subagent/descriptor', descriptor)
        async with self.lock(sid):
            throw_aborted(signal)
            self.admitting(parent)
            self.available(sid)
            if 'childId' in spec:
                stored = await persistence.list_snapshots()
                throw_aborted(signal)
                self.admitting(parent)
                self.available(sid)
                if any(item.header.id == sid for item in stored):
                    raise SubagentError('subagent already exists: ' + sid, 'DUPLICATE_CHILD')
            activation = await self.materialize(sid, spec['provider'], parent, options, descriptor, signal,
                                                dict(seed=staged.events, meta=meta, policy=policy))
            try:
                message_id = self.submit(activation, request['prompt'], {'kind': 'user'}, parent, signal)
            except BaseException:
                await self.dispose(activation)
                raise
        return dict(childId=sid, messageId=message_id)

    async def followup(self, parent, sid, content, options=None):
        options = options or {}
        signal = options.get('signal', NEVER_ABORTED)
        while True:
            self.admitting(parent)
            throw_aborted(signal)
            async with self.lock(sid):
                activation = self.activations.get(sid)
                if activation is not None and activation.disposal is not None:
                    await asyncio.gather(asyncio.shield(activation.disposal), return_exceptions=True)
                    continue
                if activation is not None:
                    return self.submit(activation, content, options.get('source', {'kind': 'user'}), parent, signal)
                query = self.require('sessionQuery')
                observation = await query.observeSession(sid, {'signal': signal, 'projectionMode': 'none'})
                try:
                    self.authorize(parent, observation.header.parentSession)
                    descriptor = fold_descriptor(observation.events[observation.header.seedLength or 0:])
                    if descriptor is None or descriptor['mode'] != 'continuable':
                        raise SubagentError('session is not a continuable subagent', 'NOT_RESUMABLE')
                    agent_options = AgentOptions(provider=descriptor.get('agentProvider'), model=descriptor.get('agentModel'),
                                                 reasoningEffort=descriptor.get('agentReasoningEffort'))
                    activation = await self.materialize(sid, descriptor['provider'], parent, agent_options, descriptor, signal)
                    try:
                        return self.submit(activation, content, options.get('source', {'kind': 'user'}), parent, signal)
                    except BaseException:
                        await self.dispose(activation)
                        raise
                finally:
                    observation.dispose()

    async def materialize(self, sid, provider, parent, options, composition, signal, create=None):
        self.admitting(parent)
        lineage = self.lineage(parent)
        barrier = asyncio.get_event_loop().create_future()
        self.materializations[barrier] = lineage
        try:
            def setup(child_ctx):
                if create is not None:
                    append_policy(child_ctx.agent.session, create['policy'])
                apply_composition(child_ctx, parent, composition)
                return self.setups.apply(child_ctx)
            throw_aborted(signal)
            factory = self.owner_ctx.get('agents')
            if create is None:
                handle = await factory.resume(dict(resumeSessionId=sid, agentOptions=options, signal=signal, setup=setup))
            else:
                handle = await factory.create(dict(sessionId=sid, agentOptions=options, signal=signal,
                                                   setup=setup, seed=create['seed'], meta=create['meta']))
            activation = SimpleNamespace(id=sid, parent=parent.id, provider=provider, handle=handle,
                ancestry=weakref.WeakSet(lineage + [handle.agent]), children=set(), accepted=set(),
                disposal=None, announced=False, poke=asyncio.Event(), boundary=len(handle.agent.session.events),
                run_id=str(uuid.uuid4()), watcher=None)
            self.activations[sid] = activation
            try:
                throw_aborted(signal)
                self.admitting(parent)
                self.acquire(parent, sid)
                def dequeued(payload):
                    activation.accepted.discard(payload['message']['id'])
                    activation.poke.set()
                handle.agent.ctx.on('agent/inbox/claimed', dequeued)
                handle.agent.ctx.on('agent/inbox/discarded', dequeued)
                self.edge('start', activation, parent)
            except BaseException:
                await self.dispose(activation)
                raise
            activation.watcher = asyncio.create_task(self.watch(activation))
            activation.watcher.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            return activation
        finally:
            self.materializations.pop(barrier, None)
            barrier.set_result(None)

    def acquire(self, parent, sid):
        owner = self.activations.get(parent.id)
        if owner is not None:
            if owner.handle.agent is not parent or owner.disposal is not None:
                raise SubagentError('parent activation is closing', 'ACTIVATION_CLOSING')
            owner.children.add(sid)
            owner.poke.set()

    def waking(self, activation, message, send):
        activation.accepted.add(message['id'])
        try:
            send(message)
        except BaseException:
            activation.accepted.discard(message['id'])
            raise
        activation.poke.set()
        return message['id']

    def submit(self, activation, content, source, parent, signal):
        throw_aborted(signal)
        self.admitting(parent)
        if activation.disposal is not None:
            raise SubagentError('child activation is closing', 'ACTIVATION_CLOSING')
        self.authorize(parent, activation.handle.agent.session.header.parentSession)
        self.acquire(parent, activation.id)
        message = create_user_message(dict(content=content, source=source))
        identity = self.waking(activation, message, activation.handle.agent.followup)
        activation.announced = True
        return identity

    def state(self, activation):
        if activation.handle.agent.status == 'running' or activation.accepted:
            return 'running'
        return 'waiting' if activation.children else 'settled'

    def interrupt(self, sid, authority):
        ancestor = authority.get('agent') if authority['kind'] == 'ancestor' else None
        if ancestor is not None and (self.ctx.get('agents').get(ancestor.id) is not ancestor or ancestor.id == sid):
            raise SubagentError('interrupt requires an exact live ancestor', 'UNAUTHORIZED')
        activation = self.activations.get(sid)
        if activation is None:
            return
        if (authority['kind'] == 'user' and authority.get('parentSessionId') != activation.parent or
                authority['kind'] == 'ancestor' and ancestor not in activation.ancestry):
            raise SubagentError('interrupt authority does not own this child', 'UNAUTHORIZED')
        if activation.disposal is None:
            activation.handle.agent.cancel({'kind': 'user'}, keep_inbox=True)

    def report(self, child, content, options=None):
        options = options or {}
        throw_aborted(options.get('signal', NEVER_ABORTED))
        self.admitting(child)
        activation = self.activations.get(child.id)
        if activation is None or activation.handle.agent is not child or self.ctx.get('agents').get(child.id) is not child:
            raise SubagentError('report requires the exact live continuable child', 'UNAUTHORIZED')
        if activation.disposal is not None:
            raise SubagentError('child activation is closing', 'ACTIVATION_CLOSING')
        parent = self.ctx.get('agents').get(activation.parent)
        if parent is None:
            raise SubagentError('parent is not live', 'PARENT_NOT_LIVE')
        message = create_user_message(dict(content=[dict(type='text', text='Background subagent {} reported:'.format(child.id))] + content,
                                          source=dict(kind='subagent-report', form='relay', senderSessionId=child.id)))
        if options.get('delivery', 'next-step') == 'next-step':
            owner = self.activations.get(parent.id)
            if owner is not None:
                return self.waking(owner, message, parent.steer)
            return parent.steer(message)
        return parent.inject(message)

    async def drain_descendants(self, parents):
        roots = [parent for parent in parents if self.ctx.get('agents').get(parent.id) is parent]
        if not roots:
            return
        for root in roots:
            self.closing_scopes.setdefault(root, weakref.WeakSet()).add(root)
        targets = []
        for activation in self.activations.values():
            owners = [root for root in roots if root is not activation.handle.agent and root in activation.ancestry]
            if owners:
                targets.append(activation)
                for root in owners:
                    self.closing_scopes[root].update(self.lineage(activation.handle.agent))
        materializations = []
        for barrier, lineage in self.materializations.items():
            owners = [root for root in roots if root in lineage]
            if owners:
                materializations.append(barrier)
                for root in owners:
                    self.closing_scopes[root].update(lineage)
        for activation in targets:
            self.dispose(activation)
        await asyncio.gather(*materializations, return_exceptions=True)
        await self.dispose_roots(targets)

    async def drain_children(self, parent, child_ids):
        self.authorize(parent, parent.id)
        targets = []
        for sid in set(child_ids):
            activation = self.activations.get(sid)
            if activation is None:
                continue
            if activation.parent != parent.id or parent not in activation.ancestry:
                raise SubagentError('selected child is not a direct child', 'UNAUTHORIZED')
            targets.append(activation)
        await self.dispose_roots(targets)

    async def watch(self, activation):
        while activation.disposal is None:
            activation.poke.clear()
            idle = asyncio.create_task(activation.handle.agent.when_idle())
            poked = asyncio.create_task(activation.poke.wait())
            try:
                await asyncio.wait([idle, poked], return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (idle, poked):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(idle, poked, return_exceptions=True)
            async with self.lock(activation.id):
                if activation.disposal is not None:
                    return
                if self.state(activation) == 'settled':
                    disposal = self.dispose(activation)
                    break
            if activation.handle.agent.status != 'running':
                await activation.poke.wait()
        else:
            return
        await asyncio.shield(disposal)

    def edge(self, name, activation, parent, result=None):
        payload = dict(runId=activation.run_id, provider=activation.provider, id=activation.id, local=True)
        if result is not None:
            payload['stopReason'] = result['stopReason']
            if result['output']:
                payload['lastAssistantMessage'] = result['output']
        emit_contained(self.ctx, 'subagent/' + name, payload, parent, self.host)

    def dispose(self, activation):
        if activation.disposal is not None:
            return activation.disposal
        # Publish the cutoff before cancellation can synchronously re-enter.
        done = asyncio.get_event_loop().create_future()
        activation.disposal = done
        done.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        activation.handle.agent.cancel({'kind': 'parent'})
        children = [self.dispose(self.activations[sid]) for sid in list(activation.children) if sid in self.activations]
        activation.poke.set()
        async def close():
            failures = [error for error in await asyncio.gather(*children, return_exceptions=True) if isinstance(error, BaseException)]
            child = activation.handle.agent
            result = dict(output=[], stopReason='error')
            try:
                await child.when_idle()
                try:
                    await child.session.flush()
                except Exception:
                    logging.getLogger(__name__).exception('failed to flush child final state')
                result = read_result(child, activation.boundary, child.is_cancelled())
            except BaseException as error:
                failures.append(error)
            try:
                await activation.handle.dispose()
            except BaseException as error:
                failures.append(error)
            self.activations.pop(activation.id, None)
            if failures:
                result['stopReason'] = 'error'
            parent = self.ctx.get('agents').get(activation.parent)
            if activation.announced and parent is not None:
                self.notify(parent, activation, result)
            for owner in self.activations.values():
                owner.children.discard(activation.id)
                owner.poke.set()
            self.edge('end', activation, parent, result)
            if failures:
                done.set_exception(SubagentError('; '.join(str(error) for error in failures), 'ACTIVATION_TEARDOWN_FAILED'))
            else:
                done.set_result(None)
        asyncio.create_task(close())
        return done

    def notify(self, parent, activation, result):
        endings = {'completed': 'finished and will do no further work unless you send it more.',
                   'aborted': 'was stopped before it finished.', 'max-tokens': 'ran out of room before it finished.',
                   'refusal': 'declined the task.', 'error': 'failed before it finished.'}
        summary = 'Background subagent {} {}'.format(activation.id, endings.get(result['stopReason'], 'ended abnormally.'))
        short = summary.encode('utf-16-le', errors='surrogatepass')[:240].decode('utf-16-le', errors='surrogatepass')
        message = create_user_message(dict(content=[dict(type='text', text=summary)] +
            (result['output'] or [dict(type='text', text='It left no closing message.')]),
            source=dict(kind='subagent-settled', form='notice', summary=short, senderSessionId=activation.id)))
        try:
            closing = self.draining or any(parent in members for members in self.closing_scopes.values())
            owner = self.activations.get(parent.id)
            closing = closing or owner is not None and owner.disposal is not None
            if closing:
                parent.inject(message)
            else:
                send = parent.steer if parent.status == 'running' else parent.followup
                if owner is not None:
                    self.waking(owner, message, send)
                else:
                    send(message)
        except Exception:
            logging.getLogger(__name__).exception('failed to deliver child settlement')

    async def drain(self):
        self.draining = True
        await asyncio.gather(*list(self.materializations), return_exceptions=True)
        await self.dispose_roots(list(self.activations.values()))

    async def dispose_roots(self, activations):
        results = await asyncio.gather(*(self.dispose(item) for item in activations), return_exceptions=True)
        failures = [error for error in results if isinstance(error, BaseException)]
        if failures:
            raise SubagentError('; '.join(str(error) for error in failures), 'ACTIVATION_TEARDOWN_FAILED')
