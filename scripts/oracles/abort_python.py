"""Observe actual native signals and Inspect against the platform probe."""
import asyncio
from types import SimpleNamespace

from dsh.cordis.context import Context
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController, AbortSignal, AbortError
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_registry import CordisInspectRegistryService
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.core.system_prompt import SystemPrompt
from dsh.guard.timeout_policy import ToolCallTimeoutPolicyPlugin

REASONS = ['omitted', 'undefined', 'null', 'false', 'zero', 'empty', 'string', 'object', 'error']
EMPTY = dict(type='object', properties={}, additionalProperties=False)
MANIFEST = dict(id='probe', description='Read', methods=[dict(name='read', description='Read', inputSchema=EMPTY, outputSchema=EMPTY)])


def stop(controller, name):
    error = RuntimeError('fixture abort')
    error.name, error.message = 'Error', 'fixture abort'
    values = dict(undefined=UNDEFINED, null=None, false=False, zero=0, empty='',
        string='cancelled', object=dict(caller=['operator', False]), error=error)
    controller.abort() if name == 'omitted' else controller.abort(values[name])


def value(reason):
    if not isinstance(reason, BaseException):
        return reason
    result = dict(name=getattr(reason, 'name', 'Error'), message=getattr(reason, 'message', str(reason)))
    if isinstance(reason, AbortError):
        result['code'] = reason.code
    return result


def thrown(error):
    return dict(thrown=value(error.value if isinstance(error, ThrownValueError) else error))


async def attempt(fn):
    try:
        result = fn()
        if asyncio.iscoroutine(result):
            result = await result
        return dict(value=UNDEFINED if result is None else result)
    except Exception as error:
        return thrown(error)


async def observe():
    rows = []
    for name in REASONS:
        c, events = AbortController(), []
        signal = c.signal
        before = signal.reason is None
        signal.addEventListener('abort', lambda e: events.append(dict(type=e.type, target=e.target is signal, reason=value(signal.reason))), dict(once=True))
        stop(c, name)
        first = signal.reason
        same = False
        def run():
            nonlocal same
            try:
                signal.throwIfAborted()
            except Exception as error:
                same = (error.value if isinstance(error, ThrownValueError) else error) is first
                raise
        raised = await attempt(run)
        c.abort('ignored')
        signal.addEventListener('abort', lambda e: events.append(dict(late=True)))
        rows.append(dict(mode='platform/' + name, before=before, reason=value(signal.reason), raised=raised,
            same=same, retained=signal.reason is first, events=events))
        for mode in ['host-before', 'host-after', 'client-before', 'client-pending']:
            ctx, controller, events, calls = Context(), AbortController(), [], []
            registry = CordisInspectRegistryService(ctx)
            def query(*_):
                calls.append(True)
                if mode == 'host-after':
                    stop(controller, name)
                return {}
            registry.register(dict(manifest=MANIFEST, query=query))
            registry.syncClientManifest([MANIFEST])
            ctx.on('cordis/inspect-query', lambda request: events.append(dict(request=request['requestId'])))
            ctx.on('cordis/inspect-query-resolved', lambda request: events.append(dict(resolved=request['requestId'])))
            if mode.endswith('before'):
                stop(controller, name)
            pending = asyncio.create_task(attempt(lambda: registry.query('host' if mode.startswith('host') else 'client', 'probe', 'read', UNDEFINED, SimpleNamespace(id='owner'), controller.signal)))
            if mode == 'client-pending':
                await asyncio.sleep(0)
                assert events == [dict(request='inspect-1')]
                stop(controller, name)
            rows.append(dict(mode=mode + '/' + name, result=await pending, calls=len(calls), events=events))
            await ctx.fiber.dispose()
        ctx, caller, events, entered = Context(), AbortController(), [], asyncio.Event()
        observed = {}
        try:
            await ctx.plugin(SystemPrompt)
            await ctx.plugin(ToolsPlugin)
            await ctx.plugin(ToolCallTimeoutPolicyPlugin)
            async def tool(_args, exec):
                signal = exec.signal
                observed['derived'] = signal is not caller.signal
                signal.throwIfAborted()
                ready = asyncio.Event()
                def notify(event):
                    events.append(dict(type=event.type, target=event.target is signal))
                    ready.set()
                signal.addEventListener('abort', notify, dict(once=True))
                entered.set()
                await ready.wait()
                def raise_abort():
                    try:
                        signal.throwIfAborted()
                    except Exception as error:
                        observed['same'] = (error.value if isinstance(error, ThrownValueError) else error) is caller.signal.reason
                        raise
                observed['raised'] = await attempt(raise_abort)
                signal.addEventListener('abort', lambda e: events.append(dict(late=True)))
                return [dict(type='text', text='done')]
            ctx.get('tools').register(dict(name='probe', description='read signal', parameters={}, timeoutMs=10000, execute=tool,
                output=dict(schema={}, render=lambda _args, result: result)))
            pending = asyncio.create_task(ctx.get('tools').execute(ToolExecutionInput('probe', 'probe', {}, signal=caller.signal)))
            await entered.wait()
            stop(caller, name)
            result = await pending
            rows.append(dict(mode='tools-fused/' + name, **observed, events=events, isError=result.is_error, code=result.error['info']['code']))
        finally:
            await ctx.fiber.dispose()
    c, seen = AbortController(), []
    def second(e):
        seen.append('second')
    def first(e):
        seen.append('first')
        c.signal.removeEventListener('abort', second)
    c.signal.addEventListener('abort', first)
    c.signal.addEventListener('abort', first)
    c.signal.addEventListener('abort', second)
    c.abort(None)
    rows.append(dict(mode='platform/duplicate-and-removal-during-dispatch', seen=seen))
    signal = AbortSignal.abort(None)
    rows.append(dict(mode='platform/static-abort-null', aborted=signal.aborted, result=await attempt(signal.throwIfAborted)))
    return rows
