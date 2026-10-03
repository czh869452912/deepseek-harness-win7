import asyncio

from dsh.acp.codec import turn_end_to_stop_reason
from dsh.acp.content import AcpContentError, admit_acp_prompt, check_signal
from dsh.acp.model_control import resolved
from dsh.acp.updates import assistant_updates, tool_call_update, tool_result_update
from dsh.core.abort import AbortController
from dsh.llm.error import error_chain
from dsh.llm.message import create_user_message


class AcpSession:
    def __init__(self, agent, dispose_fn=None, model_control=None, ctx=None, notify=None):
        self.agent = agent
        self.dispose_fn = dispose_fn
        self.model_control = model_control
        self.ctx = ctx
        self.notify = notify
        self.inflight_prompt = None
        self.closing = None
        self.output_tail = None
        self.pending_selections = {}
        self.topology_tasks = set()

    def cancel_prompt(self, detail):
        inflight = self.inflight_prompt
        if inflight is None:
            return
        inflight['cancel_requested'] = True
        inflight['stop_reason'] = 'cancelled'
        controller = inflight.get('admission')
        if controller is not None:
            controller.abort(RuntimeError(detail))
        if inflight.get('message_queued') and self.agent is not None:
            self.agent.cancel({'kind': 'user'})

    async def prompt(self, ctx, params, image_enabled, signal=None):
        if self.closing is not None:
            raise ValueError('session is closing')
        if self.inflight_prompt is not None:
            raise ValueError('a prompt is already in flight for this session')
        inflight = {'msg_id': None, 'turn': None, 'stop_reason': 'end_turn', 'cancel_requested': False,
                    'end_reason': None, 'agent_error': None, 'output_error': None, 'message_queued': False,
                    'selection': self.model_control.snapshot() if self.model_control is not None else None,
                    'admission': AbortController(), 'admission_done': asyncio.Event()}
        self.inflight_prompt = inflight
        detach = signal.add_listener('abort', lambda reason: self.cancel_prompt('ACP prompt request cancelled')) if signal is not None else None
        pending = asyncio.create_task(self._run_prompt(ctx, params, image_enabled, inflight))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            self.cancel_prompt('ACP prompt observer cancelled')
            pending.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
            raise
        finally:
            if detach is not None:
                detach()

    def _assert_owned(self, ctx):
        if self.dispose_fn is not None and ctx.get('agents').get(self.agent.id) is not self.agent:
            raise RuntimeError('the agent was disposed outside the bridge')

    async def _run_prompt(self, ctx, params, image_enabled, inflight):
        try:
            selection = inflight['selection']
            admission_failure = None
            try:
                self._assert_owned(ctx)
                content = await admit_acp_prompt(ctx, selection, params.get('prompt', []), image_enabled, inflight['admission'].signal)
                check_signal(inflight['admission'].signal)
                self._assert_owned(ctx)
                message = create_user_message({'content': content, 'source': {'kind': 'user'}})
                inflight['msg_id'] = message['id']
                inflight['message_queued'] = True
                if selection is not None:
                    self.pending_selections[message['id']] = selection
                try:
                    self.agent.followup(message)
                except Exception:
                    inflight['message_queued'] = False
                    self.pending_selections.pop(message['id'], None)
                    raise
            except Exception as error:
                admission_failure = error
            finally:
                inflight['admission_done'].set()
            if not inflight['cancel_requested'] and admission_failure is not None:
                if isinstance(admission_failure, AcpContentError):
                    raise admission_failure
                raise RuntimeError('prompt was not queued: ' + error_chain(admission_failure)) from admission_failure
            if inflight['message_queued']:
                await resolved(self.agent.when_idle())
                await self.drain_updates()
            if inflight['cancel_requested']:
                return {'stopReason': 'cancelled'}
            if inflight['output_error'] is not None:
                raise RuntimeError('assistant output delivery failed: ' + error_chain(inflight['output_error']))
            if inflight['agent_error'] is not None:
                raise RuntimeError('turn failed: ' + error_chain(inflight['agent_error']))
            reason = inflight['end_reason']
            if reason is not None and reason.get('kind') == 'error':
                error = reason.get('error')
                detail = error.get('message', str(error)) if isinstance(error, dict) else error_chain(error)
                raise RuntimeError('turn failed: ' + detail)
            return {'stopReason': 'cancelled' if reason is None else turn_end_to_stop_reason(reason)}
        finally:
            if self.inflight_prompt is inflight:
                self.inflight_prompt = None

    def _queue(self, operation, inflight=None, label='update delivery'):
        previous = self.output_tail
        async def deliver():
            if previous is not None:
                await asyncio.shield(previous)
            try:
                await operation()
            except Exception as error:
                if inflight is not None and inflight.get('output_error') is None:
                    inflight['output_error'] = error
                if self.ctx is not None:
                    self.ctx.logger.warn('acp: %s failed: %s' % (label, error_chain(error)))
        self.output_tail = asyncio.create_task(deliver())

    async def drain_updates(self):
        if self.output_tail is not None:
            await asyncio.shield(self.output_tail)

    def on_session_event(self, event):
        event_type = event.get('type') if isinstance(event, dict) else getattr(event, 'type', '')
        data = event.get('data', {}) if isinstance(event, dict) else getattr(event, 'data', {})
        inflight = self.inflight_prompt
        owned_turn = inflight if inflight is not None and inflight.get('turn') is not None and inflight['turn'] == data.get('turn') else None
        if self.notify is not None and event_type in ('assistant/message', 'tool/call', 'tool/result'):
            async def project():
                committed = {'type': event_type, 'data': data}
                if event_type == 'assistant/message':
                    updates = await assistant_updates(self.ctx, self.agent.session, committed)
                elif event_type == 'tool/call':
                    updates = [tool_call_update(committed)]
                else:
                    updates = [await tool_result_update(self.ctx, committed)]
                for update in updates:
                    await resolved(self.notify({'sessionId': self.agent.session.id, 'update': update}))
            self._queue(project, owned_turn if event_type == 'assistant/message' else None, event_type)
        if event_type == 'turn/end':
            if owned_turn is not None:
                owned_turn['end_reason'] = data.get('reason', {})
                owned_turn['stop_reason'] = turn_end_to_stop_reason(owned_turn['end_reason'])
            if self.model_control is not None:
                self.model_control.release_turn(data.get('turn'))

    def on_inbox_claimed(self, message, turn):
        if self.inflight_prompt is not None and self.inflight_prompt['msg_id'] == message.get('id'):
            self.inflight_prompt['turn'] = turn
        selection = self.pending_selections.pop(message.get('id'), None)
        if selection is not None and self.model_control is not None:
            self.model_control.pin_turn(turn, selection)

    def topology_changed(self):
        if self.closing is not None or self.model_control is None or self.notify is None:
            return
        async def discover():
            try:
                options = await self.model_control.options()
                if self.closing is None:
                    async def send():
                        await resolved(self.notify({'sessionId': self.agent.session.id,
                            'update': {'sessionUpdate': 'config_option_update', 'configOptions': options}}))
                    self._queue(send, label='config-option update')
            except Exception as error:
                self.ctx.logger.warn('acp: config-option update failed: ' + error_chain(error))
        pending = asyncio.create_task(discover())
        self.topology_tasks.add(pending)
        pending.add_done_callback(self.topology_tasks.discard)
