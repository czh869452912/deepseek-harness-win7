"""Actual Python/Node process runs against the current PTC capability seam."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


def cases():
    return [dict(name='json', python="print('ready')\nreturn {'n': 42}", typescript='console.log("ready"); return {n:42}'),
        dict(name='cwd-env', python="import os\nreturn [os.path.basename(os.getcwd()), dict(os.environ)]", typescript='return [(await import("node:path")).basename(process.cwd()),{...process.env}]'),
        dict(name='binding', python="return await tools['__proto__']({'n': 21})", typescript='return await tools["__proto__"]({n:21})'),
        dict(name='typed-error', python="try:\n    await tools.fail({})\nexcept ToolCallError as e:\n    return [str(e), e.toolName]", typescript='try {await tools.fail({})} catch(e) {return [e.message,e.toolName]}'),
        dict(name='large-binding', python="return len(await tools.large({}))", typescript='return (await tools.large({})).length'),
        dict(name='null', python='return None', typescript='return null'),
        dict(name='fresh', python='return missing', typescript='return missing'),
        dict(name='syntax', python='def =', typescript='const ='),
        dict(name='invalid-output', python='return {1, 2}', typescript='return new Set([1,2])'),
        dict(name='output-limit', python="print('x'*10000)", typescript='console.log("x".repeat(10000))'),
        dict(name='timeout', python='while True:\n    pass', typescript='while(true){}'),
        dict(name='abort', python='while True:\n    pass', typescript='while(true){}')]


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.code_runtime.ptc import PythonPtcRuntime
    rows = []
    ctx = Context()
    await ctx.plugin(PythonPtcRuntime, dict(timeoutMs=5000, maxTimeoutMs=7000, maxOutputBytes=4096))
    runtime = ctx.get('ptcRuntime')
    def fail(args):
        raise ValueError('binding refused')
    bindings = [dict({'global': 'tools'}, functions={'__proto__': lambda args: dict(value=args['n']*2),
        'fail': fail, 'large': lambda args: 'x'*100000}, errorClass=dict(name='ToolCallError', memberNameProperty='toolName'))]
    try:
        for requested in ('absent', None, 1, 10000, 0, -1, True, '100', []):
            request = dict(program='', bindings=bindings, cwd=str(WORKSPACE))
            if requested != 'absent':
                request['timeoutMs'] = requested
            try:
                spec = runtime.resolve(request)
                rows.append(dict(kind='resolve', value=spec['timeoutMs'], bindingIdentity=spec['bindings'] is bindings))
            except ValueError:
                rows.append(dict(kind='resolve', rejected=True))
        for case in cases():
            controller = AbortController()
            if case['name'] == 'abort':
                controller.abort('stop')
            spec = runtime.resolve(dict(program=case['python'], bindings=bindings,
                cwd=str(WORKSPACE), timeoutMs=250 if case['name']=='timeout' else 5000, signal=controller.signal))
            result = await runtime.run(spec)
            # Messages are language/substrate diagnostics, not portable content.
            if 'error' in result:
                result = dict(error=result['error']['kind'])
            rows.append(dict(kind=case['name'], result=result))
        controller = AbortController()
        entered, settled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def slow(args):
            entered.set()
            await release.wait()
            settled.set()
            return 'done'
        pending = asyncio.create_task(runtime.run(runtime.resolve(dict(program='return await tools.slow({})',
            bindings=[dict({'global':'tools'}, functions=dict(slow=slow))], cwd=str(WORKSPACE), signal=controller.signal))))
        await entered.wait()
        controller.abort('stop')
        result = await pending
        rows.append(dict(kind='binding-abort', error=result['error']['kind'], callerOwned=not settled.is_set()))
        release.set()
        await settled.wait()
        pending = asyncio.create_task(runtime.run(runtime.resolve(dict(program='while True:\n    pass', bindings=[], cwd=str(WORKSPACE)))))
        await asyncio.sleep(.03)
        await ctx.fiber.dispose()
        rows.append(dict(kind='dispose', error=(await pending)['error']['kind']))
        for method in ('resolve', 'run'):
            try:
                value = getattr(runtime, method)(dict(program='return 1', bindings=[], cwd=str(WORKSPACE), timeoutMs=5000))
                if method == 'run':
                    await value
                rejected = False
            except RuntimeError:
                rejected = True
            rows.append(dict(kind='late-' + method, rejected=rejected))
        return rows
    finally:
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE = output / 'files' / 'workspace'
    WORKSPACE.mkdir(parents=True)
    path = output / 'cases.json'
    path.write_text(json.dumps(dict(workspace=str(WORKSPACE), cases=cases())), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_runtime.mts', scope='Actual fixed Source Node/process and Python/process PTC capability runs: timeout resolution, directory/environment, bindings/errors, output failures, hard abort and disposal. Native is an explicit stateless Python provider without confinement; Node sandbox reporting and diagnostic message bytes are outside this language-portable comparison.',
        extra_inputs=[Path(__file__).resolve(), ROOT/'dsh/code_runtime/ptc.py', ROOT/'dsh/code_runtime/process.py', ROOT/'dsh/code_runtime/worker.py', ROOT/'dsh/code_runtime/contract.py'], prepare=prepare)
