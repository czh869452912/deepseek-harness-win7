"""Private JavaScript Workflow executor; never replaces the Python PTC service.

Runs the pinned Guest in a QuickJS host realm and the user's workflow in its
separate VM realm. No filesystem, process, module loader or network APIs are
installed. Only the closed Workflow Host binding set crosses the process pipe.
This is the Win7 adaptation of the Workflow execution port, not Node/TS support.
"""
import asyncio
import hashlib
import json
from pathlib import Path

from dsh.core.abort import abort_reason_error
from dsh.core.cancellation import aborted, subscribe_abort
from .ptc_run import program, json_value


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'ptc-executor'
MANIFEST_SHA256 = 'bd125728cd49e4671104a76d13a941c838e86ea724274c73a1d0ef0c3a033902'


def bootstrap():
    if hashlib.sha256((ASSETS / 'resources.json').read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise ValueError('workflow executor manifest differs')
    manifest = json.loads((ASSETS / 'resources.json').read_text(encoding='utf-8'))
    for name, expected in manifest['resources'].items():
        path = ROOT / name
        if path.resolve().parent not in (ROOT.resolve(), ASSETS.resolve()):
            raise ValueError('workflow executor resource path differs')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('workflow executor resource differs: ' + name)
    source = (ROOT / 'ptc_guest.js').read_text(encoding='utf-8')
    opening = 'import * as vm from "node:vm";'
    closing = 'export { runWorkflowGuest };'
    if source.count(opening) != 1 or source.count(closing) != 1:
        raise ValueError('workflow Guest module envelope differs')
    source = source.replace(opening, '', 1).replace(closing, '', 1)
    return '\n'.join(((ASSETS / 'error-stack.js').read_text(encoding='utf-8'),
                      (ASSETS / 'vm.js').read_text(encoding='utf-8'), source,
                      (ASSETS / 'driver.js').read_text(encoding='utf-8')))


class QuickJsWorkflowExecutor:
    language = 'javascript'
    isolation = 'process'
    programFormat = 'function-body'
    retainsState = False
    sandboxMode = 'read-only'

    def __init__(self, runtime):
        self.runtime = runtime

    def resolve(self, request):
        if request.get('program') != program():
            raise ValueError('workflow executor requires the pinned Workflow Host program')
        if request.get('timeoutMs') is not None:
            raise ValueError('workflow executor requires holder-owned lifetime')
        bindings = request.get('bindings')
        if not isinstance(bindings, list) or len(bindings) != 1 or bindings[0].get('global') != 'workflowHost':
            raise ValueError('workflow executor requires the Workflow Host binding')
        if set(bindings[0]['functions']) != {'begin', 'startChild', 'childResult', 'disposeChild', 'progress'}:
            raise ValueError('workflow executor binding set differs')
        return dict(request)

    async def run(self, spec):
        signal = spec.get('signal')
        if aborted(signal):
            raise abort_reason_error(signal)
        functions = spec['bindings'][0]['functions']
        initial = json_value(await functions['begin']({}))
        requests, worker_ref = set(), []
        stopped = asyncio.get_event_loop().create_future()
        def abort(_reason):
            if not stopped.done():
                stopped.set_exception(abort_reason_error(signal))
        detach = subscribe_abort(signal, abort)
        async def handle(message):
            worker = worker_ref[0]
            response = dict(type='binding-result', id=message['id'])
            try:
                if message.get('name') not in functions:
                    raise ValueError('unknown workflow binding')
                operation = asyncio.ensure_future(functions[message['name']](message.get('value')))
                operation.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                response['value'] = json_value(await asyncio.shield(operation))
            except Exception as error:
                response['error'] = getattr(error, 'message', str(error))
            if not worker.closed.done():
                try:
                    await worker.send(response)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        def observe(message):
            if message['type'] == 'terminal':
                return
            if message['type'] != 'binding':
                raise ValueError('unexpected workflow executor frame')
            task = asyncio.create_task(handle(message))
            requests.add(task)
            def done(future):
                requests.discard(future)
                if not future.cancelled():
                    future.exception()
            task.add_done_callback(done)
        worker = None
        try:
            worker = await self.runtime.open(dict(body=initial['body'], name='workflow:' + initial['meta']['name'],
                deferScript=True, bootstrap=bootstrap(), errorPrelude=(ASSETS / 'error-stack.js').read_text(encoding='utf-8')), observe)
            worker_ref.append(worker)
            if aborted(signal):
                raise abort_reason_error(signal)
            await worker.send(dict(type='go'))
            completed, _ = await asyncio.wait((worker.result, stopped), return_when=asyncio.FIRST_COMPLETED)
            if worker.result in completed:
                return dict(logs=[], value=worker.result.result())
            stopped.result()
        finally:
            detach()
            if not stopped.done():
                stopped.cancel()
            elif not stopped.cancelled():
                stopped.exception()
            if worker is not None:
                await worker.terminate()
            # Stop only carrier response waits. Shielded Host operations keep
            # their own child ownership and are joined by PtcWorkflowRun.finally.
            remaining = list(requests)
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
