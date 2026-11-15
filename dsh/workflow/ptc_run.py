"""Holder-owned rc.3 Workflow PTC host. Runtime and children outlive engine unload."""
import asyncio
import json
import math
from pathlib import Path
from urllib.parse import quote

from dsh.core.abort import AbortController, abort_reason_error
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.cleanup import CleanupPromise
from dsh.core.session.json import snapshot_json_value, UNDEFINED
from dsh.core.tools import assert_object_json_schema
from .workflow_service import render_error


def program():
    source = (Path(__file__).parent / 'ptc_guest.js').read_text(encoding='utf-8')
    url = 'data:text/javascript,' + quote(source, safe="~()*!.'-_")
    return 'const { runWorkflowGuest } = await import(' + json.dumps(url) + '); return await runWorkflowGuest(workflowHost);'


def object_value(value):
    if not isinstance(value, dict):
        raise ValueError('workflow binding requires an object')
    return value


def text(value, name):
    if not isinstance(value, str):
        raise ValueError('workflow %s must be a string' % name)
    return value


def integer(value, minimum=-9007199254740991):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= 9007199254740991 and int(value) == value


def json_value(value):
    result = snapshot_json_value(value, UNDEFINED)
    if result is UNDEFINED:
        raise ValueError('workflow binding value must be lossless JSON')
    return result


def field(value, key):
    return value[key] if isinstance(value, dict) else getattr(value, key)


def child_request(value):
    request = object_value(value)
    result = dict(prompt=text(request.get('prompt'), 'prompt'))
    for key in ('provider', 'model'):
        if key in request:
            result[key] = text(request[key], key)
    if 'schema' in request:
        result['schema'] = object_value(request['schema'])
        assert_object_json_schema(result['schema'])
    return result


def agent_info(value):
    info = object_value(value)
    if not integer(info.get('seq'), 1):
        raise ValueError('workflow agent sequence must be a positive integer')
    result = dict(seq=info['seq'], label=text(info.get('label'), 'agent label'),
                  childId=text(info.get('childId'), 'child id'))
    if 'phase' in info:
        result['phase'] = text(info['phase'], 'agent phase')
    return result


def progress(value):
    event = object_value(value)
    kind = event.get('type')
    if kind in ('phase', 'log'):
        key = 'title' if kind == 'phase' else 'message'
        return dict(type=kind, **{key: text(event.get(key), kind)})
    if kind == 'agent-start':
        return dict(type=kind, info=agent_info(event.get('info')))
    if kind == 'agent-end':
        info = object_value(event.get('info'))
        if info.get('outcome') not in ('completed', 'failed', 'cancelled'):
            raise ValueError('invalid workflow agent outcome')
        return dict(type=kind, info=dict(agent_info(info), outcome=info['outcome']))
    raise ValueError('invalid workflow progress event')


def workflow_result(value):
    result = object_value(value)
    if result.get('stopReason') not in ('completed', 'error', 'cancelled'):
        raise ValueError('invalid workflow stop reason')
    if not integer(result.get('agentsStarted'), 0):
        raise ValueError('invalid workflow agent count')
    if 'value' not in result:
        raise ValueError('workflow result is missing its value')
    selected = {key: result[key] for key in ('value', 'stopReason', 'agentsStarted')}
    if 'error' in result:
        selected['error'] = text(result['error'], 'error')
    return selected


class PtcWorkflowRun:
    def __init__(self, ctx, subagents, runtime, run_id, meta, parent, init,
                 provider, policy, observer, signal=None):
        self.ctx, self.subagents, self.runtime = ctx, subagents, runtime
        self.id, self.meta, self.parent, self.init = run_id, meta, parent, init
        self.provider, self.policy, self.observer = provider, policy, observer
        self.controller = AbortController()
        self.children, self.pending, self.live = {}, set(), {}
        self.started, self.terminal, self.cancel_reason = 0, False, None
        self.disposed = None
        self.detach = lambda: None
        if aborted(signal):
            self.cancel('workflow signal aborted')
        else:
            self.detach = subscribe_abort(signal, lambda *_: self.cancel('workflow signal aborted'))
        self.cwd = asyncio.ensure_future(ctx.get('workingDirectory').ensure(parent, self.controller.signal))
        self.result = asyncio.create_task(self.drive())

    def cancel(self, reason='workflow cancelled'):
        if self.terminal or self.cancel_reason is not None:
            return
        self.cancel_reason = reason
        self.controller.abort(reason)
        for record in list(self.children.values()):
            self.dispose_child(record)

    def dispose(self):
        self.cancel('workflow disposed')
        if self.disposed is None:
            async def finish():
                await asyncio.shield(self.result)
            self.disposed = CleanupPromise(finish())
        return self.disposed

    def require_active(self):
        self.controller.signal.throwIfAborted()

    def track(self, operation):
        task = asyncio.ensure_future(operation)
        self.pending.add(task)
        def settled(done):
            self.pending.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(settled)
        return task

    def bindings(self):
        async def begin(_value=None):
            self.require_active()
            return json_value(self.init)
        async def dispose(value):
            await self.dispose_child(self.child(value))
            return None
        async def report(value):
            if not isinstance(value, list):
                raise ValueError('workflow progress requires an array of events')
            events = [progress(item) for item in value]
            for event in events:
                self.on_progress(event)
            return None
        return dict(begin=begin, startChild=lambda value: self.track(self.start_child(child_request(value))),
                    childResult=lambda value: self.track(self.child_result(self.child(value))),
                    disposeChild=dispose, progress=report)

    def child(self, value):
        self.require_active()
        call_id = object_value(value).get('callId')
        if not integer(call_id):
            raise ValueError('workflow child call id must be an integer')
        if call_id not in self.children:
            raise ValueError('workflow child call is not active')
        return self.children[call_id]

    async def start_child(self, request):
        self.require_active()
        self.started += 1
        call_id = self.started
        spec = dict(provider=self.provider, label='%s child %s' % (self.meta['name'], call_id),
                    delivery='caller', signal=self.controller.signal, cwd=await asyncio.shield(self.cwd),
                    prompt=[dict(type='text', text=request['prompt'])], parent=self.parent)
        if 'schema' in request:
            spec['outputSchema'] = request['schema']
        options = {key: request[key] for key in ('provider', 'model') if key in request}
        if options:
            spec['agentOptions'] = options
        run = await self.subagents.startActivation(spec)
        record = dict(callId=call_id, run=run)
        self.children[call_id] = record
        if self.controller.signal.aborted:
            await self.dispose_child(record)
            raise ValueError('workflow child started after cancellation')
        return dict(callId=call_id, childId=field(run, 'childId'))

    async def child_result(self, record):
        self.require_active()
        signal = self.controller.signal
        cancelled = asyncio.get_event_loop().create_future()
        def abort(_reason):
            if not cancelled.done():
                cancelled.set_exception(abort_reason_error(signal))
        detach = subscribe_abort(signal, abort)
        try:
            child_result = field(record['run'], 'result')
            completed, _ = await asyncio.wait((child_result, cancelled), return_when=asyncio.FIRST_COMPLETED)
            # Promise.race registers the result first; preserve that order when both settled.
            result = child_result.result() if child_result in completed else cancelled.result()
            selected = dict(output=result.get('output', UNDEFINED), stopReason=result.get('stopReason', UNDEFINED))
            if 'structured' in result:
                selected['structured'] = result['structured']
            return json_value(selected)
        finally:
            detach()
            if not cancelled.done():
                cancelled.cancel()
            elif not cancelled.cancelled():
                cancelled.exception()

    def dispose_child(self, record):
        if 'disposal' not in record:
            async def cleanup():
                try:
                    await field(record['run'], 'dispose')()
                except Exception as error:
                    self.ctx.logger.warn('workflow-ptc: child dispose failed: ' + render_error(error))
                finally:
                    self.children.pop(record['callId'], None)
            record['disposal'] = CleanupPromise(cleanup())
        return record['disposal']

    def end_agent(self, info):
        if self.live.pop(info['seq'], None) is not None:
            self.observer.agentEnd(info)

    def on_progress(self, event):
        self.require_active()
        kind = event['type']
        if kind == 'phase':
            self.observer.phase(event['title'])
        elif kind == 'log':
            self.observer.log(event['message'])
        elif kind == 'agent-start':
            self.live[event['info']['seq']] = event['info']
            self.observer.agentStart(event['info'])
        else:
            self.end_agent(event['info'])

    def cancelled(self):
        return dict(value=None, stopReason='cancelled', error='workflow run cancelled: ' + self.cancel_reason,
                    agentsStarted=self.started)

    async def drive(self):
        try:
            cwd = await asyncio.shield(self.cwd)
            self.require_active()
            confined = getattr(self.runtime, 'sandboxMode', None) is not None
            if not confined and self.policy['mode'] != 'danger-full-access':
                raise ValueError('workflow runtime cannot enforce the %s file policy' % self.policy['mode'])
            body = program()
            formats = {'function-body': body, 'repl': 'await (async () => {\n' + body + '\n})()',
                       'script': '(async () => {\n' + body + '\n})()'}
            request = dict(program=formats[self.runtime.programFormat], bindings=[dict(global_='workflowHost', functions=self.bindings())],
                           cwd=cwd, timeoutMs=None, signal=self.controller.signal)
            request['bindings'][0]['global'] = request['bindings'][0].pop('global_')
            if confined:
                request['sandboxPolicy'] = self.policy
            outcome = await self.runtime.run(self.runtime.resolve(request))
            self.terminal = True
            if self.cancel_reason is not None:
                result = self.cancelled()
            elif 'error' in outcome:
                error = outcome['error']
                result = dict(value=None, stopReason='error', error='workflow execution failed (%s): %s' % (error['kind'], error['message']), agentsStarted=self.started)
            else:
                result = workflow_result(outcome.get('value'))
        except Exception as error:
            self.terminal = True
            result = self.cancelled() if self.cancel_reason is not None else dict(value=None, stopReason='error', error=render_error(error), agentsStarted=self.started)
        finally:
            self.terminal = True
            self.detach()
            self.controller.abort('workflow settled')
            for record in list(self.children.values()):
                self.dispose_child(record)
            while self.pending:
                await asyncio.gather(*list(self.pending), return_exceptions=True)
            await asyncio.gather(*(self.dispose_child(record) for record in list(self.children.values())))
            self.children.clear()
            for info in list(self.live.values()):
                self.end_agent(dict(info, outcome='cancelled'))
        return result
