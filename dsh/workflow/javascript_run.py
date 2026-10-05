import asyncio
import logging

from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.tools import _json_snapshot
from dsh.cordis.utils import _UNDEFINED
from .workflow_service import WorkflowResult, emit_workflow, render_error


logger = logging.getLogger(__name__)


class JavaScriptWorkflowRun:
    def __init__(self, ctx, runtime, subagents, run_id, meta, parent, route, script, args, limits, signal):
        self.id, self.meta, self.parent, self.route = run_id, meta, parent, route
        self.ctx, self.runtime, self.subagents, self.limits = ctx, runtime, subagents, limits
        self.info = dict(id=run_id, meta=_json_snapshot(meta))
        self.result = asyncio.get_event_loop().create_future()
        self.result.add_done_callback(self._emit_end)
        self.controller = AbortController()
        self._worker, self._reason, self._timer, self._disposal = None, None, None, None
        self._terminal, self._death_observed, self._host_started = False, False, 0
        self._children, self._live = {}, {}
        self._starts, self._tasks, self._forwards = set(), set(), set()
        self._quiet = asyncio.Event()
        self._quiet.set()
        self._detach = lambda: None
        initial = dict(body=script, meta=meta, limits={key: limits[key] for key in (
            'maxConcurrentAgents', 'maxTotalAgents', 'maxItemsPerCall', 'syncTimeoutMs')})
        if args is not _UNDEFINED:
            initial['args'] = args
        self._opening = self._own(self._open(initial))
        if signal is not None:
            if aborted(signal):
                self.cancel('workflow start signal already aborted')
            else:
                self._detach = subscribe_abort(signal, lambda *_: self.cancel('workflow signal aborted'))

    def _own(self, coroutine, collection=None):
        collection = self._tasks if collection is None else collection
        task = asyncio.create_task(coroutine)
        collection.add(task)
        def settled(future):
            collection.discard(future)
            if not future.cancelled():
                future.exception()
            self._notify_quiet()
        task.add_done_callback(settled)
        return task

    async def _open(self, initial):
        try:
            worker = await self.runtime.open_workflow(initial, self._message, self.limits['disposeGraceMs'])
            self._worker = worker
            worker.closed.add_done_callback(lambda _: self._worker_closed())
            if self._terminal or self._death_observed:
                await worker.terminate()
            elif self._reason is not None:
                await worker.cancel(self._reason)
            else:
                await worker.send(dict(type='go'))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if getattr(error, 'code', None) == 'WORKER_EXIT':
                self._death('workflow worker exited before the run settled (exit code {})'.format(error.exit_code))
            else:
                self._death('workflow worker failed: ' + render_error(error))

    def _worker_closed(self):
        failure = self._worker.failure
        if failure is not None and getattr(failure, 'code', None) != 'WORKER_EXIT':
            self._death('workflow worker failed: ' + render_error(failure))
        else:
            self._death('workflow worker exited before the run settled (exit code {})'.format(self._worker.process.returncode))

    def _post(self, kind, **payload):
        async def post():
            worker = self._worker
            if worker is None or worker.closed.done():
                return
            try:
                await worker.send(dict(type=kind, **payload))
            except Exception:
                logger.warning('workflow-worker-thread: postMessage failed', exc_info=True)
        self._own(post())

    async def _message(self, message):
        if self._death_observed:
            return
        kind = message['type']
        if kind in ('phase', 'log'):
            if self._reason is None:
                emit_workflow(self.ctx, 'workflow/' + kind, self.info, message['title' if kind == 'phase' else 'message'])
        elif kind == 'agent-start':
            info = message['info']
            self._live[info['seq']] = info
            emit_workflow(self.ctx, 'workflow/agent-start', self.info, info)
        elif kind == 'agent-end':
            self._end(message['info'])
        elif kind == 'child-start':
            failure = self._admission_failure()
            if failure is not None:
                self._post('child-start-error', callId=message['callId'], rendered=failure)
                return
            self._host_started += 1
            self._quiet.clear()
            entered = asyncio.Event()
            self._own(self._start_child(message['callId'], message['request'], entered), self._starts)
            await entered.wait()
        elif kind == 'child-dispose':
            self._own(self._ack_disposal(message['callId']))
        elif kind == 'terminal':
            if self._terminal:
                return
            cancellation_requested = self._reason is not None
            self._terminal = True
            self._reap('workflow settled')
            result = message['result']
            if cancellation_requested and result['stopReason'] != 'cancelled':
                result = self._cancelled(result['agentsStarted'])
            self._settle(result)
            await asyncio.sleep(0)
        else:
            raise RuntimeError('unexpected workflow worker message: ' + kind)

    def _admission_failure(self):
        if self._reason is not None:
            return 'workflow run cancelled: ' + self._reason
        if self._death_observed:
            return 'workflow worker is no longer available'
        if self._terminal:
            return 'workflow run already settled'
        return None

    async def _start_child(self, call_id, request, entered):
        child_request = dict(prompt=[dict(type='text', text=request['prompt'])],
                             parent=self.parent, signal=self.controller.signal)
        if 'schema' in request:
            child_request['outputSchema'] = request['schema']
        overrides = {key: request[key] for key in ('provider', 'model') if key in request}
        if overrides:
            child_request['agentOptions'] = overrides
        entered.set()
        try:
            run = await self.subagents.start(self.route, child_request)
        except Exception as error:
            self._post('child-start-error', callId=call_id, rendered=self._admission_failure() or render_error(error))
            return
        failure = self._admission_failure()
        if failure is not None:
            self._post('child-start-error', callId=call_id, rendered=failure)
            try:
                await run.dispose()
            except Exception:
                logger.warning('workflow-worker-thread: refused child dispose failed', exc_info=True)
            return
        record = dict(run=run, disposal=None)
        self._children[call_id] = record
        self._own(self._forward_result(call_id, run), self._forwards)
        self._post('child-started', callId=call_id, childId=run.id)

    async def _forward_result(self, call_id, run):
        try:
            result = await asyncio.shield(run.result)
        except Exception as error:
            self._post('child-failed', callId=call_id, rendered=render_error(error))
            return
        try:
            projected = dict(output=result['output'], stopReason=result['stopReason'])
            if 'structured' in result and result['structured'] is not _UNDEFINED:
                projected['structured'] = result['structured']
            snapshot = _json_snapshot(projected)
        except Exception as error:
            self._post('child-failed', callId=call_id,
                       rendered='workflow child result could not cross the worker boundary: ' + render_error(error))
            return
        self._post('child-settled', callId=call_id, result=snapshot)

    async def _ack_disposal(self, call_id):
        record = self._children.get(call_id)
        if record is not None:
            await asyncio.shield(self._dispose_child(call_id, record))
        self._post('child-disposed', callId=call_id)

    def _dispose_child(self, call_id, record):
        if record['disposal'] is None:
            async def dispose():
                try:
                    await record['run'].dispose()
                except Exception:
                    logger.warning('workflow-worker-thread: child dispose failed', exc_info=True)
                finally:
                    if self._children.get(call_id) is record:
                        del self._children[call_id]
                    self._notify_quiet()
            record['disposal'] = self._own(dispose())
        return record['disposal']

    def _notify_quiet(self):
        if not self._starts and not self._children:
            self._quiet.set()

    def _reap(self, reason):
        if not self.controller.signal.aborted:
            self.controller.abort(self._reason if self._reason is not None else reason)
        for call_id, record in list(self._children.items()):
            self._dispose_child(call_id, record)

    def _end(self, info):
        if self._live.pop(info['seq'], None) is not None:
            emit_workflow(self.ctx, 'workflow/agent-end', self.info, info)

    def _end_stranded(self):
        for info in list(self._live.values()):
            self._end(dict(info, outcome='cancelled'))

    def _cancelled(self, started):
        return WorkflowResult(stop_reason='cancelled', error='workflow run cancelled: ' + (
            self._reason if self._reason is not None else 'workflow cancelled'), agents_started=started).to_dict()

    def _settle(self, result):
        if self.result.done():
            return
        self._terminal = True
        self._detach()
        if self._timer is not None:
            self._timer.cancel()
        self.result.set_result(result)

    def _emit_end(self, future):
        if future.cancelled():
            return
        result = future.result()
        emit_workflow(self.ctx, 'workflow/end', self.info,
                      {key: result[key] for key in ('stopReason', 'error', 'agentsStarted') if key in result})

    def _death(self, message):
        if not self._death_observed:
            self._death_observed = True
            claimed = self._terminal
            self._terminal = True
            if self._starts or self._children:
                self._reap('workflow worker gone')
            self._end_stranded()
            if not claimed:
                self._settle(self._cancelled(self._host_started) if self._reason is not None else
                    WorkflowResult(stop_reason='error', error=message, agents_started=self._host_started).to_dict())
        for task in list(self._forwards):
            task.cancel()
        for call_id, record in list(self._children.items()):
            self._dispose_child(call_id, record)
        self._end_stranded()

    def cancel(self, reason=None):
        if self._terminal or self._reason is not None:
            return
        self._reason = 'workflow cancelled' if reason is None else reason
        if self._worker is not None:
            self._post('cancel', reason=self._reason)
        if not self.controller.signal.aborted:
            self.controller.abort(self._reason)
        def force():
            self._terminal = True
            self._end_stranded()
            self._settle(self._cancelled(self._host_started))
            if self._worker is not None:
                self._own(self._worker.terminate())
        self._timer = asyncio.get_event_loop().call_later(self.limits['disposeGraceMs'] / 1000, force)

    def dispose(self):
        if self._disposal is None:
            self._disposal = asyncio.get_event_loop().create_future()
            self._detach()
            self.cancel('workflow disposed')
            self._reap('workflow disposed')
            async def dispose():
                async def quiesce():
                    await asyncio.shield(self.result)
                    await self._quiet.wait()
                wait = asyncio.create_task(quiesce())
                try:
                    await asyncio.wait_for(asyncio.shield(wait), self.limits['disposeGraceMs'] / 1000)
                except asyncio.TimeoutError:
                    wait.cancel()
                    await asyncio.gather(wait, return_exceptions=True)
                finally:
                    if self._worker is None and not self._opening.done():
                        self._opening.cancel()
                    await asyncio.gather(asyncio.shield(self._opening), return_exceptions=True)
                    if self._worker is not None:
                        await self._worker.terminate()
                        self._death('workflow worker disposed')
                    elif not self.result.done():
                        self._death('workflow worker disposed during creation')
                    self._reap('workflow disposed')
            task = self._own(dispose())
            def settled(future):
                if future.cancelled():
                    self._disposal.cancel()
                elif future.exception() is not None:
                    self._disposal.set_exception(future.exception())
                else:
                    self._disposal.set_result(None)
            task.add_done_callback(settled)
        return self._disposal
