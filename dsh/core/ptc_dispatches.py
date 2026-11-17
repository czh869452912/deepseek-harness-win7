"""One PTC run's ordered policy lane and concurrent nested tool bodies."""
import asyncio
import logging
from collections import deque

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.cordis.utils import js_to_string
from dsh.core.tools import ToolExecutionInput, _json_snapshot, _deep_freeze, _error_message
from dsh.llm.message import create_user_message


class ToolCallLimitExceededError(RuntimeError):
    name = 'ToolCallLimitExceededError'

    def __init__(self, limit, number, per_minute):
        self.message = ('run_code exceeded its limit of %s tool calls (%s per minute of its timeout); '
            'call %s was not dispatched. The run_code program may contain an infinite loop. '
            'Check loop termination or split the work into smaller run_code calls.'
            % (limit, per_minute, number))
        super().__init__(self.message)


class PtcDispatches:
    def __init__(self, ctx, pipeline, execution, controller, max_parallel, max_calls, calls_per_minute):
        self.ctx, self.pipeline, self.execution, self.controller = ctx, pipeline, execution, controller
        self.max_parallel, self.max_calls, self.calls_per_minute = max_parallel, max_calls, calls_per_minute
        self.attempts = 0
        self.pending, self.commits = deque(), deque()
        self.in_flight, self.log_work = set(), set()
        self.exclusive = self.driving = False
        self.driver = None
        self.wake = asyncio.Event()

    def binding(self, schema):
        schema = _deep_freeze(_json_snapshot(schema))
        # JS async functions count and queue synchronously before returning
        # their Promise. Match that prefix before returning the Python Future.
        return lambda arguments: start_coroutine(self._call(schema, arguments))

    def _over_message(self, name, suffix):
        reason = self.controller.signal.reason
        if isinstance(reason, BaseException):
            error_name, message = getattr(reason, 'name', 'Error'), str(_error_message(reason))
            text = error_name + ': ' + message if error_name and message else error_name or message
        else:
            text = js_to_string(reason)
        return 'run_code run is over (%s); %s %s' % (text, name, suffix)

    async def _call(self, schema, raw):
        name = schema['name']
        if self.controller.signal.aborted:
            raise RuntimeError(self._over_message(name, 'not dispatched'))
        self.attempts += 1
        number = self.attempts
        if number > self.max_calls:
            error = ToolCallLimitExceededError(self.max_calls, number, self.calls_per_minute)
            self.controller.abort(error)
            raise error
        try:
            arguments = _json_snapshot(raw)
        except Exception as error:
            raise ValueError('tool arguments must be lossless JSON: ' + str(_error_message(error)))
        outer = self.execution
        sub_id = '%s:ptc:%s' % (outer.call_id, number)
        execution = ToolExecutionInput(sub_id, name, arguments, agent=outer.agent,
            signal=self.controller.signal, root_call_id=outer.root_call_id,
            parent=outer.token, toolSet=outer.toolSet, schema=schema)
        entry = dict(input=execution, logged=_json_snapshot(arguments), settled=False,
            outcome=None, mode=None, result=asyncio.get_running_loop().create_future())
        self.pending.append(entry)
        self.wake.set()
        self._drive()
        result = await asyncio.shield(entry['result'])
        if self.controller.signal.aborted:
            raise RuntimeError(self._over_message(name, 'result discarded'))
        if result.is_error:
            raise RuntimeError(result.error['message'])
        # Tool results are frozen for observers. The process binding wire owns
        # a detached JSON value, just as the Source's JSON serialization does.
        return _json_snapshot(result.value)

    def _drive(self):
        if not self.driving:
            self.driving = True
            self.driver = start_coroutine(self._driver())
        return self.driver

    async def _driver(self):
        try:
            while True:
                self.wake.clear()
                if self.commits and self.commits[0]['settled']:
                    entry = self.commits.popleft()
                    await self._commit(entry)
                    if entry['mode'] == 'exclusive':
                        self.exclusive = False
                    continue
                if self.pending:
                    entry = self.pending[0]
                    if self.controller.signal.aborted:
                        self.pending.popleft()
                        entry['result'].set_exception(RuntimeError(self._over_message(entry['input'].name, 'tool call abandoned')))
                        continue
                    mode = self.pipeline.execution_mode(entry['input'])['kind']
                    capacity = (not self.exclusive and
                        (not self.in_flight if mode == 'exclusive' else len(self.in_flight) < self.max_parallel))
                    if capacity:
                        self.pending.popleft()
                        self.commits.append(entry)
                        entry['mode'] = mode
                        if mode == 'exclusive':
                            self.exclusive = True
                        await self._start(entry)
                        flight = entry.get('flight')
                        if flight is None:
                            flight = asyncio.get_running_loop().create_future()
                            flight.set_result(None)
                        self.in_flight.add(flight)
                        flight.add_done_callback(self._body_finished)
                        continue
                if not self.pending and not self.commits and not self.in_flight:
                    return
                await self.wake.wait()
        finally:
            self.driving = False

    def _body_finished(self, future):
        self.in_flight.discard(future)
        self.wake.set()

    def _event_data(self, entry):
        return dict(rootCallId=self.execution.root_call_id, parentCallId=self.execution.call_id,
            subCallId=entry['input'].call_id, name=entry['input'].name, arguments=entry['logged'])

    async def _start(self, entry):
        if self.execution.agent is not None:
            self.execution.agent.session.append('tool/ptc-dispatch-start', self._event_data(entry))
        prepared = await await_callback_result(self.pipeline.prepare(entry['input']))
        entry['exec'] = prepared['exec']
        if prepared['kind'] != 'dispatch':
            entry['outcome'], entry['settled'] = prepared, True
            return

        async def body():
            entry['outcome'] = await await_callback_result(self.pipeline.dispatch(prepared['exec']))
            entry['settled'] = True
        entry['flight'] = start_coroutine(body())

    async def _commit(self, entry):
        result = await await_callback_result(self.pipeline.complete(entry['exec'], entry['outcome']))
        if not result.is_error and any(block['type'] == 'image' for block in result.content):
            self.execution.deferContext(create_user_message(dict(content=result.content, source=dict(kind='ptc-mode'))))
        for context in result.additional_contexts:
            self.execution.deferContext(context)
        if result.concludes_turn:
            self.execution.concludeTurn()
        entry['result'].set_result(result)
        if self.execution.agent is not None:
            task = start_coroutine(self._log(entry, result))
            self.log_work.add(task)
            task.add_done_callback(self.log_work.discard)
        while len(self.log_work) > self.max_parallel:
            done, _ = await asyncio.wait(self.log_work, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()

    async def _log(self, entry, result):
        dispatch = dict(exec=self.execution, agent=self.execution.agent,
            subCallId=entry['input'].call_id, name=entry['input'].name,
            isError=result.is_error, content=result.content)
        try:
            content = await await_callback_result(self.pipeline._carrier(self.execution).waterfall(
                'tools/ptc-dispatch-log', dispatch, lambda *_args: result.content))
        except Exception as error:
            logging.getLogger('tools').warning('tools: ptc-dispatch-log listener failed for %s: %s; logging the original settled content',
                entry['input'].name, _error_message(error))
            content = result.content
        data = self._event_data(entry)
        data.update(isError=result.is_error, content=content)
        if result.error is not None and result.error.get('info') is not None:
            data['error'] = result.error['info']
        if result._meta_present:
            data['meta'] = result.meta
        self.execution.agent.session.append('tool/ptc-dispatch', data)

    async def drain(self):
        # The caller aborts the run before draining; pending calls are then
        # abandoned unlogged, and every started pipeline/log settles in-turn.
        self.wake.set()
        await asyncio.shield(self._drive())
        while self.log_work:
            await asyncio.gather(*list(self.log_work), return_exceptions=True)
