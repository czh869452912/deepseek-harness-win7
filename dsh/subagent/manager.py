"""Unified v4 subagent creation, target-only restoration and tree delivery."""
import asyncio
import os
import uuid
from types import SimpleNamespace

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.core.agent import AgentOptions
from dsh.core.cancellation import subscribe_abort
from dsh.core.abort import AbortController
from dsh.core.session.json import UNDEFINED
from dsh.llm.message import create_user_message
from dsh.subagent.activation import observe_local_failure,require_local_activation
from dsh.subagent.catalog import establish_catalog_child,establish_external_catalog_child
from dsh.subagent.child_agent import (resolveChildDepth,resolveChildAgentOptions,child_session_meta,
    capture_delegated_policy_overrides,append_delegated_policy_overrides,apply_child_composition)
from dsh.subagent.descriptor import snapshot_descriptor,fold_descriptor
from dsh.subagent.errors import SubagentError
from dsh.subagent.lifetime import SubagentLifetime,future,contain
from dsh.subagent.messages import create_agent_message,with_result_delivery_guidance
from dsh.subagent.names import join_agent_path,agent_address
from dsh.subagent.structured import attach_structured_runtime
from dsh.subagent.archive_admission import install_subagent_archive_admission
from dsh.subagent.tree import activation_agent


def has_image(content):
    return any(block.get('type') == 'image' for block in content)


class SubagentManager(SubagentLifetime):
    def __init__(self, ctx, host, max_active_subagents):
        super().__init__(ctx,host,max_active_subagents)
        def ancestors(agent):
            activation = self.resident.get(agent.id)
            return activation.ancestors if activation is not None and activation_agent(activation) is agent else None
        install_subagent_archive_admission(ctx,ancestors,host.identityOf)

    def require_persistence(self):
        persistence = self.ctx.get('sessionPersistence')
        if persistence is None:
            raise SubagentError('continuable subagents require session persistence (load a dsh-session-persistence backend)',
                                'PERSISTENCE_UNAVAILABLE')
        return persistence

    def assert_child_id_available(self, child_id):
        sessions = self.ctx.get('sessions')
        if child_id in self.resident or self.ctx.get('agents').get(child_id) is not None or sessions is not None and sessions.get(child_id) is not None:
            raise SubagentError('subagent "%s" already exists' % child_id,'DUPLICATE_CHILD')

    async def resolve_directory(self, request, signal):
        requested = request.get('cwd')
        if requested is not None and os.path.isabs(requested):
            cwd = requested
        else:
            inherited = await self.ctx.get('workingDirectory').ensure(request['parent'],signal)
            cwd = os.path.abspath(os.path.join(inherited,requested if requested is not None else '.'))
        signal.throwIfAborted()
        return cwd

    def start_local(self, spec, prepare):
        parent = spec['parent']
        self.assert_admitting(parent)
        ancestry = self.ancestry_for_child(parent)
        reservation = self.reserve_name(parent,spec.get('name',UNDEFINED))
        path = join_agent_path(self.path_of(parent,ancestry['root']),reservation.name)
        async def start(signal):
            persistence = self.ctx.get('sessionPersistence') if spec.get('delivery') == 'caller' else self.require_persistence()
            child_id = spec.get('childId',str(uuid.uuid4()))
            self.assert_child_id_available(child_id)
            depth = resolveChildDepth(parent,spec.get('maxDepth'))
            options = resolveChildAgentOptions(parent,spec.get('agentOptions'),depth)
            descriptor = dict(mode='continuable',provider=spec['provider'],label=spec['label'])
            for option,key in (('provider','agentProvider'),('model','agentModel'),('reasoningEffort','agentReasoningEffort')):
                value = getattr(options,option,None)
                if value is not None:
                    descriptor[key] = value
            descriptor = snapshot_descriptor(descriptor)
            policies = capture_delegated_policy_overrides(parent)
            cwd = await self.resolve_directory(spec,signal)
            prepared = await prepare(dict(sessionId=child_id,cwd=cwd,parent=parent,signal=signal))
            signal.throwIfAborted()
            self.assert_admitting(parent)
            seed = prepared.get('seed')
            async with self.locks.hold(child_id):
                signal.throwIfAborted()
                self.assert_admitting(parent)
                self.assert_child_id_available(child_id)
                if 'childId' in spec:
                    persisted = await persistence.stat(child_id,dict(signal=signal)) if persistence is not None else None
                    signal.throwIfAborted()
                    self.assert_admitting(parent)
                    self.assert_child_id_available(child_id)
                    if persisted is not None:
                        raise SubagentError('subagent "%s" already exists' % child_id,'DUPLICATE_CHILD')
                activation = await self.materialize(dict(kind='local',childId=child_id,provider=spec['provider'],
                    **ancestry,path=path,create=dict(parent=parent,cwd=cwd,seed=seed,
                        meta=child_session_meta(parent,depth,seed is not None,spec.get('agentPreset')),
                        inheritedEventCount=len(seed) if seed is not None else 0,delegatedPolicies=policies,descriptor=descriptor),
                    agentOptions=options,composition={key:spec[key] for key in ('agentPreset',) if key in spec},signal=signal,
                    delivery=spec.get('delivery'),outputSchema=spec.get('outputSchema')))
                child = require_local_activation(activation).handle.agent
                def commit():
                    self.assert_admitting(parent)
                    establish_catalog_child(parent.session,child.session.header,descriptor,reservation.name)
                prompt = spec['prompt'] if spec.get('delivery') == 'caller' else with_result_delivery_guidance(spec['prompt'])
                message_id = await self.submit_materialized(activation,prompt,dict(source=dict(kind='user'),signal=signal,
                    delivery='queue',authorize=lambda:self.assert_admitting(parent)),ancestry['root'],commit)
            return dict(self.receipt(activation),childId=child_id,messageId=message_id)
        async def perform():
            try:
                return await self.track_startup(ancestry['root'],spec['signal'],start)
            finally:
                reservation.release()
        return start_coroutine(perform())

    def start_external(self, spec, start_provider):
        parent, delivery = spec['parent'],spec.get('delivery')
        self.assert_admitting(parent)
        ancestry = self.ancestry_for_child(parent)
        if delivery == 'caller' and 'name' in spec:
            raise SubagentError('agent names require a cataloged child; caller-delivered external runs are not cataloged','UNSUPPORTED_CAPABILITY')
        reservation = self.reserve_name(parent,spec.get('name',UNDEFINED)) if delivery == 'parent' else None
        path = join_agent_path(self.path_of(parent,ancestry['root']),reservation.name if reservation is not None else UNDEFINED)
        async def start(signal):
            activation = None
            try:
                cwd = await self.resolve_directory(spec,signal)
                request = {key:value for key,value in spec.items() if key not in ('provider','delivery','childId','name')}
                activation = await self.materialize(dict(kind='external',provider=spec['provider'],**ancestry,path=path,
                    signal=signal,delivery=delivery,start=lambda signal:start_provider(dict(request,cwd=cwd,signal=signal))))
                self.assert_admitting(parent)
                signal.throwIfAborted()
                if reservation is not None:
                    establish_external_catalog_child(parent.session,activation.childId,spec.get('label'),reservation.name)
                self.accept(activation)
                return self.receipt(activation)
            except BaseException:
                if activation is not None:
                    try:
                        await asyncio.shield(self.dispose(activation))
                    except Exception as error:
                        self.ctx.logger.warn('subagent "%s" admission rollback failed: %s' % (activation.childId,error))
                raise
        async def perform():
            try:
                return await self.track_startup(ancestry['root'],spec['signal'],start)
            finally:
                if reservation is not None:
                    reservation.release()
        return start_coroutine(perform())

    def materialize(self, inputs):
        self.assert_admitting(inputs['root'])
        inputs['signal'].throwIfAborted()
        release = self.root_pool(inputs['root']).reserve(self.max_active_subagents())
        async def perform():
            try:
                return await self.materialize_tracked(inputs,release)
            except BaseException:
                release()
                raise
        return start_coroutine(perform())

    async def materialize_tracked(self, inputs, release):
        signal = inputs['signal']
        signal.throwIfAborted()
        if inputs['kind'] == 'external':
            controller = AbortController()
            unhook = subscribe_abort(signal,lambda reason:controller.abort(reason))
            try:
                run = await inputs['start'](controller.signal)
                contain(run.result)
                try:
                    self.assert_child_id_available(run.id)
                except BaseException:
                    await run.dispose()
                    raise
                resource = dict(kind='external',run=run,controller=controller)
            finally:
                unhook()
        else:
            create, structured = inputs.get('create'),None
            composition = inputs['composition']
            async def setup(child_ctx, child):
                nonlocal structured
                parent = create['parent'] if create is not None else None
                if composition.get('agentPreset') is not None:
                    await await_callback_result(apply_child_composition(child_ctx,parent,composition))
                if create is not None:
                    if composition.get('agentPreset') is not None:
                        child.session.append('agent-preset/selected',dict(agentPreset=composition['agentPreset']))
                    child.session.append('subagent/descriptor',create['descriptor'])
                    append_delegated_policy_overrides(child.session,create['delegatedPolicies'])
                    directory = child_ctx.get('workingDirectory')
                    if directory is None:
                        raise RuntimeError('local subagents require the working-directory service')
                    await directory.set(child,create['cwd'],signal)
                if composition.get('agentPreset') is None:
                    await await_callback_result(apply_child_composition(child_ctx,parent,composition))
                if inputs.get('outputSchema') is not None:
                    structured = attach_structured_runtime(child_ctx,inputs['outputSchema'],lambda:not child.inbox.nextStep and not child.inbox.nextTurn)
            args = dict(agentOptions=inputs['agentOptions'],signal=signal,setup=setup)
            agents = self.owner_ctx.get('agents')
            if create is None:
                handle = await agents.resume(dict(args,resumeSessionId=inputs['childId']))
            else:
                args.update(sessionId=inputs['childId'],meta=create['meta'],inheritedEventCount=create['inheritedEventCount'])
                if create['seed'] is not None:
                    args['seed'] = create['seed']
                handle = await agents.create(args)
            resource = dict(kind='local',handle=handle,outputStart=handle.agent.session.seq,structured=structured,
                            failureAt=None,poke=future(),omitClosingText=False)
        child_id = resource['handle'].agent.id if resource['kind'] == 'local' else resource['run'].id
        activation = SimpleNamespace(**resource,releaseSlot=release,childId=child_id,runId=str(uuid.uuid4()),
            provider=inputs['provider'],root=inputs['root'],ancestors=inputs['ancestors'],path=inputs['path'],
            delivery=inputs.get('delivery') or 'parent',result=contain(future()),closing=None,accepted=False)
        self.resident[child_id] = activation
        try:
            self.assert_admitting(activation.root)
            signal.throwIfAborted()
            if activation.kind == 'local':
                child = activation.handle.agent
                observe_local_failure(activation,lambda:self.wake(activation))
                child.ctx.on('agent/inbox/inserted',lambda *args:self.wake(activation))
                child.ctx.on('agent/inbox/discarded',lambda *args:self.wake(activation))
                def claimed(*args):
                    activation.omitClosingText = False
                    self.wake(activation)
                def event(_session,event):
                    if event['type'] == 'tool/call':
                        activation.omitClosingText = False
                child.ctx.on('agent/inbox/claimed',claimed)
                child.ctx.on('session/event',event)
            self.host.emitLifecycle('subagent/start',self.run_info(activation),activation.root)
        except BaseException as error:
            try:
                await self.rollback_unpublished(activation,error)
            except Exception:
                pass
            raise
        return activation

    async def assert_image_capable(self, agent, signal):
        provider,model = agent.options.provider,agent.options.model
        llm = self.ctx.get('llm')
        if provider is None or model is None or llm is None:
            return
        info = await llm.resolveModelInfo(provider,model,signal)
        if 'inputModalities' in info and 'image' not in info['inputModalities']:
            raise SubagentError('Model "%s" does not support image input.' % model,'MODEL_DOES_NOT_SUPPORT_IMAGES')

    def submit_admitted(self, activation, content, options, parent):
        message = create_user_message(dict(content=content,source=options['source']))
        options['signal'].throwIfAborted()
        if options.get('authorize') is not None:
            options['authorize']()
        self.assert_admitting(parent)
        try:
            self.deliver(activation,message,options['delivery'])
        finally:
            self.wake(activation)
        if options.get('onAccepted') is not None:
            options['onAccepted']()
        return message['id']

    async def submit_materialized(self, activation, content, options, parent, commit=None):
        try:
            if has_image(content):
                await self.assert_image_capable(require_local_activation(activation).handle.agent,options['signal'])
                if activation.closing is not None:
                    raise SubagentError('subagent "%s" is closing' % activation.childId,'ACTIVATION_CLOSING')
            message_id = self.submit_admitted(activation,content,options,parent)
            if commit is not None:
                commit()
            self.accept(activation)
            return message_id
        except BaseException:
            try:
                await asyncio.shield(self.dispose(activation))
            except Exception as error:
                self.ctx.logger.warn('subagent continuation: disposal after admission or catalog append failure also failed: '+str(error))
            raise

    async def restore_target(self, root, child_id, signal):
        async def restore(signal):
            source = await self.observe_continuation(child_id,signal)
            try:
                self.assert_admitting(root)
                descriptor = fold_descriptor(source.events[int(source.inheritedEventCount):])
                if descriptor is None or descriptor['mode'] != 'continuable':
                    raise SubagentError('subagent "%s" has no supported continuation state and cannot be resumed; choose a different target' % child_id,'NOT_RESUMABLE')
                ancestry = await self.resolve_creation_ancestry(source,signal,root)
                try:
                    preset = source.projections.get('values',{}).get('agentPreset') if source.projections is not None else None
                    if preset is None and any(event['type'] == 'agent-preset/selected' for event in source.events):
                        raise SubagentError('subagent "%s" has no agent preset projection for restoration' % child_id,'NOT_RESUMABLE')
                    if preset is None:
                        preset = source.header.get('agentPreset')
                    options = AgentOptions(provider=descriptor.get('agentProvider'),model=descriptor.get('agentModel'),reasoningEffort=descriptor.get('agentReasoningEffort'))
                    composition = {key:descriptor[key] for key in ('persona','toolFilter') if key in descriptor}
                    if preset is not None:
                        composition['agentPreset'] = preset
                    return await self.materialize(dict(kind='local',childId=child_id,provider=descriptor['provider'],**ancestry,
                        agentOptions=options,composition=composition,signal=signal))
                except Exception as cause:
                    signal.throwIfAborted()
                    if isinstance(cause,SubagentError):
                        raise
                    error = SubagentError('subagent "%s" is unavailable' % child_id,'NOT_RESUMABLE')
                    error.cause = cause
                    raise error
            finally:
                source.dispose()
        return await self.track_startup(root,signal,restore)

    async def deliver_to_member(self, root, child_id, content, options):
        while True:
            self.assert_admitting(root)
            options['signal'].throwIfAborted()
            async with self.locks.hold(child_id):
                if child_id == root.id:
                    if has_image(content):
                        await self.assert_image_capable(root,options['signal'])
                    options['signal'].throwIfAborted()
                    if options.get('authorize') is not None:
                        options['authorize']()
                    self.assert_admitting(root)
                    message = create_user_message(dict(content=content,source=options['source']))
                    self.send_waking(root,message,options['delivery'])
                    if options.get('onAccepted') is not None:
                        options['onAccepted']()
                    return message['id']
                activation = self.resident.get(child_id)
                if activation is None:
                    restored = await self.restore_target(root,child_id,options['signal'])
                    return await self.submit_materialized(restored,content,options,root)
                if activation.root is not root:
                    raise SubagentError('target belongs to another subagent tree','UNAUTHORIZED')
                require_local_activation(activation)
                if activation.closing is None and has_image(content):
                    await self.assert_image_capable(activation.handle.agent,options['signal'])
                closing = activation.closing
                if closing is None:
                    return self.submit_admitted(activation,content,options,root)
            await asyncio.gather(asyncio.shield(closing),return_exceptions=True)

    async def send_message(self, sender, target_id, content, options):
        options['signal'].throwIfAborted()
        root = self.root_of(sender)
        if sender.id == target_id:
            raise SubagentError('send_message requires another agent in the subagent tree','UNAUTHORIZED')
        self.assert_admitting(sender)
        message = create_agent_message(sender,agent_address(self.path_of(sender,root),sender.id),content)
        activation = self.resident.get(sender.id)
        def accepted():
            if activation is not None and activation.kind == 'local' and activation.ancestors[-1] == target_id:
                activation.omitClosingText = True
        return await self.deliver_to_member(root,target_id,list(message['content']),dict(signal=options['signal'],delivery='steer',
            source=message['source'],authorize=lambda:self.assert_admitting(sender),onAccepted=accepted))

    async def deliver_prompt(self, child_id, content, options):
        options['signal'].throwIfAborted()
        activation = self.resident.get(child_id)
        root = activation.root if activation is not None else None
        if root is None:
            source = await self.observe_continuation(child_id,options['signal'])
            try:
                root = (await self.resolve_creation_ancestry(source,options['signal']))['root']
            finally:
                source.dispose()
        return await self.deliver_to_member(root,child_id,content,options)

    startLocal = start_local
    startExternal = start_external
    sendMessage = send_message
    deliverPrompt = deliver_prompt
