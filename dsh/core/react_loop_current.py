"""rc.3 Agent machine: every model request derives from the durable v3 surface."""
import asyncio
import copy
import inspect

from dsh.cordis.awaiting import await_callback_result, resume_coroutine
from dsh.cordis.errors import AggregateError
from dsh.core.abort import AbortController
from dsh.core.agent import AgentOptions
from dsh.core.agent_dispatch_current import agent_events, assemble_context_for
from dsh.core.assistant_stream_current import AssistantStreamAttempt
from dsh.core.inbox_current import ReactLoopInbox
from dsh.core.model_selection import AgentModel
from dsh.core.runtime_context_current import RuntimeContextProjection, SystemPromptProjection
from dsh.core.scope import create_scope
from dsh.core.session.current_request_header import canonicalHeader, headerEquals
from dsh.core.session.json import UNDEFINED, FrozenDict, FrozenList, deep_freeze
from dsh.core.system_prompt import render_prompt, render_context_sections, join_context_sections
from dsh.core.tool_calls import execute_tool_calls
from dsh.llm.agent_request import mark_agent_loop_request
from dsh.llm.error import error_chain
from dsh.llm.llm_service import LlmError
from dsh.llm.message import create_assistant_message
from dsh.llm.stream_bridge import iter_chunks


def request_proposal(header):
    config = dict(header['config'])
    for key in ('reasoningEffort', 'maxTokens'):
        if header.get('adapterDefaults', {}).get(key) is True:
            config.pop(key, None)
    return config


class ReactLoopAgent:
    def __init__(self, loop_ctx, session, options=None, inbox_reader=None, model_reader=None, lifetime_signal=None):
        self.loop_ctx, self.session, self.id = loop_ctx, session, session.id
        self.lifetime_signal = lifetime_signal
        self.options = options or AgentOptions()
        self.model = AgentModel(model_reader, session, self.options) if model_reader is not None else None
        self.request_header_logged = False
        self.request_surface_generation = session.surface.replaceGeneration
        self.dispatch = agent_events(loop_ctx, self)
        self.scope = create_scope(loop_ctx, self)
        self.ctx = self.scope.ctx
        self.inbox = ReactLoopInbox(inbox_reader if inbox_reader is not None
                                    else self.ctx.get('sessionProjections'), session, self.dispatch)
        boundary = (loop_ctx.get('agents').turnBoundaryOf(session) if getattr(session,'format_version',3) == 4
                    else loop_ctx.get('sessionProjections').stateOf(session, 'turnBoundary'))
        self.phase = dict(kind='idle', lastTurn=boundary['lastTurn'] if boundary else 0)
        self.activity_done = asyncio.get_running_loop().create_future()
        self.activity_done.set_result(None)
        self._driver_task = None
        self.runtime_context = RuntimeContextProjection(self.ctx, session)
        self.system_prompt = SystemPromptProjection(session)
        self.stream_revision = self.attempt_counter = 0

    @property
    def status(self):
        return 'running' if self.phase['kind'] == 'running' else 'idle'

    def _set_phase(self, phase):
        previous = self.status
        self.phase = phase
        if self.status != previous:
            self.dispatch.emit('agent/status', dict(status=self.status))

    def send(self, message, target='next-turn', wakeup=True):
        waking_after_abort = wakeup and self.phase['kind'] != 'idle' and self.phase['abort'].signal.aborted
        self.inbox.append('next-turn' if waking_after_abort else target, message)
        if wakeup:
            self._wake_driver(waking_after_abort)

    def followup(self, message):
        self.send(message, 'next-turn', True)

    def steer(self, message):
        self.send(message, 'next-step', True)

    def inject(self, message):
        self.send(message, 'next-step', False)

    def cancel(self, cause=None, options=None, keep_inbox=False):
        keep = keep_inbox or (options.get('keepInbox', False) if isinstance(options, dict)
                             else getattr(options, 'keepInbox', False))
        if getattr(self.session,'format_version',3) != 4:
            if not keep:
                self.inbox.clear()
                if self.phase['kind'] != 'idle':self.phase['wakeRequested'] = False
            if self.phase['kind'] != 'idle':self.phase['abort'].abort(cause if cause is not None else dict(kind='user'))
            return
        try:
            if not keep:self.inbox.clear()
        finally:
            if self.phase['kind'] != 'idle':
                if not keep:self.phase['wakeRequested'] = False
                self.phase['abort'].abort(cause if cause is not None else dict(kind='user'))

    def run_maintenance(self, job):
        if self.phase['kind'] != 'idle':
            raise RuntimeError('agent "%s" already has active work' % self.id)
        done = asyncio.get_running_loop().create_future()
        phase = dict(kind='maintenance', abort=AbortController(), lastTurn=self.phase['lastTurn'], wakeRequested=False)
        self._set_phase(phase)
        self.activity_done = done
        async def perform():
            try:
                return await await_callback_result(job(phase['abort'].signal))
            finally:
                self._set_phase(dict(kind='idle', lastTurn=phase['lastTurn']))
                reason=phase['abort'].signal.reason
                disposed=isinstance(reason,dict) and reason.get('kind')=='disposed'
                if (not disposed or getattr(self.session,'format_version',3) != 4) and phase['wakeRequested'] and self.inbox.hasPending:
                    self._wake_driver()
                done.set_result(None)
        return self._start(perform())

    runMaintenance = run_maintenance

    @staticmethod
    def _start(coroutine):
        """Enter the synchronous JS async-function prefix before returning its task."""
        try:
            awaited = coroutine.send(None)
        except StopIteration as stop:
            result = asyncio.get_running_loop().create_future()
            result.set_result(stop.value)
            return result
        except BaseException as error:
            result = asyncio.get_running_loop().create_future()
            result.set_exception(error)
            return result
        return asyncio.create_task(resume_coroutine(coroutine, awaited))

    def _wake_driver(self, wake_after_abort=False):
        if self.lifetime_signal is not None and self.lifetime_signal.aborted:
            return
        if self.phase['kind'] != 'idle':
            reason = self.phase['abort'].signal.reason
            disposed = isinstance(reason, dict) and reason.get('kind') == 'disposed'
            if not disposed and (self.phase['kind'] == 'maintenance' or wake_after_abort):
                self.phase['wakeRequested'] = True
            return
        done = asyncio.get_running_loop().create_future()
        self.activity_done = done
        self._set_phase(dict(kind='running', abort=AbortController(), turn=self.phase['lastTurn'], step=0, wakeRequested=False))
        agents = self.loop_ctx.get('agents')
        if getattr(agents, 'format_version', 3) == 4:
            async def driver():
                try:
                    await self._kick()
                finally:
                    done.set_result(None)
            self._driver_task = agents.withInitiator(self, lambda:self._start(driver()))
            return
        # The eager prefix and every continuation run under the same initiator.
        from dsh.core.agent import _CURRENT_INITIATOR
        agents._enter_initiator_run()
        token = _CURRENT_INITIATOR.set(self)
        async def driver():
            try:
                await self._kick()
            finally:
                agents._leave_initiator_run()
                done.set_result(None)
        try:
            self._driver_task = self._start(driver())
        finally:
            _CURRENT_INITIATOR.reset(token)

    async def when_idle(self):
        while True:
            activity = self.activity_done
            await asyncio.shield(activity)
            if activity is self.activity_done:
                return

    whenIdle = when_idle

    def _throw_error(self, error):
        running = self.phase['kind'] == 'running'
        self.dispatch.emit('agent/error', dict(turn=self.phase['turn'] if running else self.phase['lastTurn'],
                                               step=self.phase['step'] if running else 0, error=error))
        raise error

    async def _kick(self):
        try:
            while await self._turn():
                pass
        except BaseException:
            pass
        finally:
            if self.phase['kind'] == 'running':
                phase = self.phase
                self._set_phase(dict(kind='idle', lastTurn=phase['turn']))
                if phase['wakeRequested'] and self.inbox.hasPending:
                    self._wake_driver()

    async def _pre_step(self, target, turn, step):
        signal = self.phase['abort'].signal
        claimed = self.inbox.claim(target, turn)
        selection = self.model.current() if self.model is not None else None
        if selection is UNDEFINED:
            raise RuntimeError('agent "%s" has no provider/model: set AgentOptions.provider and AgentOptions.model or record a model selection' % self.id)
        context = assemble_context_for(self, signal)
        if selection is not None:
            context['modelSelection'] = selection
        assembly = await await_callback_result(self.loop_ctx.get('systemPrompt').assemble(context))
        signal.throwIfAborted()
        sections = render_context_sections(assembly)
        context = self.runtime_context.project(join_context_sections(sections), sections)
        payload = dict(messages=claimed, turn=turn, step=step, signal=signal)
        if selection is not None:
            payload['modelSelection'] = selection
        decision = await await_callback_result(self.dispatch.waterfall('agent/pre-step', payload,
            lambda: dict(kind='enter', messages=claimed if context is None else claimed + [context])))
        signal.throwIfAborted()
        return decision if decision['kind'] == 'reject' else dict(decision, assembly=assembly, selection=selection)

    def _tools_changed(self, tools):
        baseline = self.session.requestHeader()
        return baseline is not None and not headerEquals(baseline, canonicalHeader(dict(baseline, tools=list(tools))))

    async def _turn(self):
        phase = self.phase
        signal = phase['abort'].signal
        signal.throwIfAborted()
        turn = phase['turn'] + 1
        try:
            self.session.append('turn/start', dict(turn=turn))
        except BaseException as error:
            self._throw_error(error)
        phase['turn'] = turn
        ending, target = None, 'next-turn'
        try:
            while True:
                signal.throwIfAborted()
                step = phase['step'] + 1
                decision = await await_callback_result(self._pre_step(target, turn, step))
                if decision['kind'] == 'reject':
                    ending = dict(kind='blocked')
                    return False
                if ending is not None and not decision['messages']:
                    break
                if phase['step'] == 0 and not decision['messages']:
                    ending = dict(kind='completed')
                    return False
                signal.throwIfAborted()
                self.session.append('step/start', dict(turn=turn, step=step))
                phase['step'] = step
                try:
                    step_end = await await_callback_result(self._step(decision))
                    if ending is None or ending['kind'] != 'max-tokens':
                        ending = step_end
                finally:
                    self.session.append('step/end', dict(turn=turn, step=step))
                signal.throwIfAborted()
                if ending is not None and not self.inbox.nextStep:
                    await await_callback_result(self.dispatch.serial('agent/turn-stopping', dict(turn=turn, signal=signal)))
                    signal.throwIfAborted()
                if ending is not None and not self.inbox.nextStep:
                    break
                target = 'next-step'
        except BaseException as error:
            if signal.aborted:
                ending = dict(kind='aborted', reason=signal.reason)
                raise
            ending = dict(kind='error', error=error.failure if isinstance(error, LlmError)
                          else dict(message=error_chain(error), code='UNKNOWN'))
            self._throw_error(error)
        finally:
            try:
                self.session.append('turn/end', dict(turn=turn, reason=ending))
            except BaseException as error:
                self._throw_error(error)
        if not self.inbox.hasPending:
            return False
        phase.update(abort=AbortController(), wakeRequested=False, step=0)
        return True

    def _next_revision(self):
        self.stream_revision += 1
        return self.stream_revision

    async def _step(self, decision):
        turn, step, signal = self.phase['turn'], self.phase['step'], self.phase['abort'].signal
        signal.throwIfAborted()
        assembly = decision['assembly']
        rendered_prompt = render_prompt(assembly)
        first_attempt = True
        while True:
            config, prepared = await await_callback_result(self._prepare_request(turn, step, signal, decision.get('selection')))
            starts_series = first_attempt and decision.get('startsRequestSeries') is True
            commits = self.system_prompt.project(rendered_prompt, dict(
                inHistory=prepared is not None and prepared.get('systemPromptUpdate') == 'in-history',
                startsSeries=starts_series or self.request_surface_generation != self.session.surface.replaceGeneration or self._tools_changed(assembly['tools'])))
            for commit in commits:
                self.session.append('system/message', dict(turn=turn, step=step, message=commit['message']), opts=commit['intent'])
            if first_attempt:
                for message in decision['messages']:
                    self.session.append('user/message', message, 'append')
            first_attempt = False
            request = self._build_request(config, prepared, assembly['tools'], starts_series, signal)
            self.attempt_counter += 1
            live = AssistantStreamAttempt(self.id, self.attempt_counter, self._next_revision, turn, step,
                                          lambda frame: self.dispatch.emit('agent/assistant-stream', dict(frame=frame)))
            started = False
            try:
                stream = prepared['stream'](request) if prepared is not None else self.loop_ctx.get('llm').stream(request)
                signal.throwIfAborted()
                live.start()
                started = True
                reader = iter_chunks(stream)
                try:
                    async for chunk in reader:
                        signal.throwIfAborted()
                        live.push(chunk)
                finally:
                    await reader.aclose()
                signal.throwIfAborted()
            except BaseException as error:
                if not started:
                    raise
                try:
                    content = live.interruptedBlocks() if signal.aborted else []
                    if content:
                        self._settle_message(live, request, content, interrupted=True)
                    else:
                        self._settle_attempt(live)
                except BaseException as settlement_error:
                    failure = AggregateError([error, settlement_error], 'Assistant stream failed and its durable settlement was rejected')
                    failure.cause = error
                    raise failure
                raise
            try:
                finish = live.finish
                if finish['kind'] in ('error', 'aborted'):
                    self._settle_attempt(live)
                    payload = dict(turn=turn, step=step, provider=request['provider'], failure=finish['failure'], signal=signal)
                    if prepared is not None and prepared.get('retryPolicy') is not None:
                        payload['retryPolicy'] = prepared['retryPolicy']
                    action = await await_callback_result(self.dispatch.waterfall('agent/request-error', payload, lambda: None))
                    signal.throwIfAborted()
                    if not isinstance(action, dict) or action.get('kind') != 'retry':
                        failure = finish['failure']
                        raise LlmError(failure['message'], failure['code'],
                                       **{key: failure[key] for key in ('status', 'providerRetryAfterMs', 'requestId') if key in failure})
                    continue
                message = self._settle_message(live, request, live.blocks())
                if finish['kind'] == 'max-tokens':
                    return dict(kind='max-tokens')
                calls = [block for block in message['content'] if block['type'] == 'tool-call']
                if not calls:
                    return dict(kind='completed')
                outcome = await await_callback_result(execute_tool_calls(self.loop_ctx, self, turn, step, calls, signal,
                    lambda context: self.inbox.splice('next-step', len(self.inbox.nextStep), 0, [context])))
                return dict(kind='completed') if outcome['concluded'] else None
            except BaseException:
                if not live.ended:
                    live.abandon()
                raise

    def _settle_attempt(self, live):
        live.settle('assistant/attempt', lambda: self.session.append('assistant/attempt',
                    dict(turn=live.turn, step=live.step, stream=live.stream))['seq'])

    def _settle_message(self, live, request, content, interrupted=False):
        source = dict(provider=request['provider'], model=request['model'])
        if live.replayState is not UNDEFINED:
            source['replayState'] = live.replayState
        message = create_assistant_message(dict(content=content, source=source))
        data = dict(turn=live.turn, step=live.step, message=message, stream=live.stream)
        if interrupted:
            data['interrupted'] = True
        if live.usage is not UNDEFINED:
            data['usage'] = live.usage
        live.settle('assistant/message', lambda: self.session.append('assistant/message', data, 'append')['seq'])
        return message

    async def _prepare_request(self, turn, step, signal, selection=None):
        persisted = self.session.requestHeader()
        route = dict(provider=self.options.provider or '', model=self.options.model or '')
        old_config = persisted['config'] if persisted is not None else {}
        effort = self.options.reasoningEffort
        if effort is None and all(old_config.get(key) == value for key, value in route.items()) and not (persisted or {}).get('adapterDefaults', {}).get('reasoningEffort'):
            effort = old_config.get('reasoningEffort')
        config = dict(route)
        if effort is not None:
            config['reasoningEffort'] = effort
        if self.options.maxTokens is not None:
            config['maxTokens'] = self.options.maxTokens
        seed = deep_freeze(copy.deepcopy(request_proposal(persisted) if self.request_header_logged else config))
        if selection is not None:
            controls = (request_proposal(persisted) if self.request_header_logged
                        else dict(maxTokens=self.options.maxTokens) if self.options.maxTokens is not None else {})
            seed = deep_freeze(copy.deepcopy(dict(
                {key: value for key, value in controls.items() if key not in ('provider', 'model', 'reasoningEffort')}, **selection)))
        proposed = await await_callback_result(self.dispatch.waterfall('agent/request', dict(turn=turn, step=step, signal=signal), lambda: seed))
        signal.throwIfAborted()
        if selection is not None:
            if any(proposed.get(key) != selection.get(key) for key in ('provider', 'model')):
                from dsh.cordis.utils import js_to_string
                raise RuntimeError('agent "%s": agent/request proposed "%s/%s" after step preparation fixed "%s/%s"; use agent.model.select() before step preparation' % (
                    self.id, js_to_string(proposed.get('provider', UNDEFINED)), js_to_string(proposed.get('model', UNDEFINED)), selection['provider'], selection['model']))
            if proposed.get('reasoningEffort', UNDEFINED) != selection.get('reasoningEffort', UNDEFINED):
                raise RuntimeError('agent "%s": agent/request proposed reasoning effort "%s" after step preparation fixed "%s"; use agent.model.select() before step preparation' % (
                    self.id, proposed.get('reasoningEffort') if proposed.get('reasoningEffort') is not None else 'adapter default',
                    selection.get('reasoningEffort') if selection.get('reasoningEffort') is not None else 'adapter default'))
        if not proposed.get('provider') or not proposed.get('model'):
            raise RuntimeError('agent "%s" has no provider/model: set AgentOptions.provider and AgentOptions.model or supply both via the agent/request waterfall' % self.id)
        prepared = None
        try:
            prepared = await await_callback_result(self.loop_ctx.get('llm').prepareCall(proposed, signal))
            config = prepared['config']
        except LlmError as error:
            if error.code != 'NO_ADAPTER':
                raise
            config = proposed
        signal.throwIfAborted()
        return config, prepared

    def _build_request(self, config, prepared, tools, starts_request_series, signal):
        generation = self.session.surface.replaceGeneration
        header = dict(config=config)
        if prepared is not None:
            header['adapterDefaults'] = prepared['adapterDefaults']
        if tools:
            # PromptAssembly offers attribute-access wrappers for native providers.
            # The durable wire boundary accepts only plain lossless JSON containers.
            header['tools'] = [dict(tool) for tool in tools]
        header = canonicalHeader(header)
        baseline = self.session.requestHeader()
        starts_series = starts_request_series or self.request_surface_generation != generation
        if not self.request_header_logged:
            self.session.append('request/header', dict(header=header, reason='initial' if baseline is None else 'resume'))
            self.request_header_logged = True
        elif baseline is None or not headerEquals(baseline, header):
            data = dict(header=header, reason='change')
            if starts_series:
                data['startsSeries'] = True
            self.session.append('request/header', data)
        elif starts_series:
            self.session.append('request/header', dict(header=header, reason='series'))
        self.request_surface_generation = generation
        request_context = dict(provider=config['provider'], model=config['model'])
        if prepared is not None:
            if 'contextWindow' in prepared.get('context', {}):
                request_context['contextWindow'] = prepared['context']['contextWindow']
            if 'systemPromptUpdate' in prepared:
                request_context['systemPromptUpdate'] = prepared['systemPromptUpdate']
        previous = self.session.requestContext()
        if previous is None or any(previous.get(key) != request_context.get(key) for key in ('provider', 'model', 'contextWindow', 'systemPromptUpdate')):
            self.session.append('request/context', request_context)
        signal.throwIfAborted()
        # Python freezes detached containers; accepted history is already frozen.
        frozen_header = deep_freeze(header)
        messages = FrozenList(self.session.deriveMessages())
        request = dict(frozen_header['config'], messages=messages, sessionId=self.id, signal=signal)
        if 'tools' in frozen_header:
            request['tools'] = frozen_header['tools']
        return mark_agent_loop_request(FrozenDict(request))
