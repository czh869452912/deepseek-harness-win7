import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys


async def observe(error_type, exited):
    from dsh.cordis.context import Context
    from dsh.javascript.runtime import JavaScriptRuntime

    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    runtime = ctx.get('jsRuntime')
    entered, release = asyncio.Event(), asyncio.Event()
    original_spawn = asyncio.create_subprocess_exec
    processes = []
    selected_error = error_type('controlled initial transport failure')

    async def spawn(*arguments, **options):
        process = await original_spawn(*arguments, **options)

        def write(payload):
            assert json.loads(payload)['body'] == 'return 1'

        async def drain():
            entered.set()
            await release.wait()
            raise selected_error

        process.stdin.write, process.stdin.drain = write, drain
        processes.append(process)
        return process

    asyncio.create_subprocess_exec = spawn
    opening = asyncio.create_task(runtime.open(dict(body='return 1', name='initial transport control',
        bootstrap='globalThis.__drive=()=>{};', args=None)))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert len(processes) == 1 and len(runtime._workers) == 1
        worker = next(iter(runtime._workers))
        assert not worker.ready.done()
        if exited:
            processes[0].kill()
            await asyncio.wait_for(processes[0].wait(), 5)
        before_cleanup = dict(exited=processes[0].returncode is not None, readySettled=worker.ready.done(),
            readyAdmitted=worker.ready.done() and not worker.ready.cancelled() and worker.ready.exception() is None)
        release.set()
        try:
            await asyncio.wait_for(opening, 5)
        except BaseException as error:
            result = dict(type=type(error).__name__, message=str(error), code=getattr(error, 'code', None),
                originalIdentity=error is selected_error, workerFailureIdentity=error is worker.failure,
                originalCause=error.__cause__ is selected_error)
        else:
            raise AssertionError('Transport failure admitted a worker')
        assert worker.closed.done() and not runtime._workers and not runtime._spawns
        return dict(name=error_type.__name__ + ('/exited' if exited else '/live'),
            beforeCleanup=before_cleanup, result=result, exitCode=processes[0].returncode,
            closed=worker.closed.done(), ownedWorkers=len(runtime._workers), ownedSpawns=len(runtime._spawns))
    finally:
        release.set()
        asyncio.create_subprocess_exec = original_spawn
        await asyncio.gather(opening, return_exceptions=True)
        await ctx.fiber.dispose()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root = options.root.resolve()
    sys.path.insert(0, str(root))
    observations = [await observe(error_type, exited) for error_type in (BrokenPipeError, ConnectionResetError)
        for exited in (False, True)]
    runtime = root / 'dsh/javascript/runtime.py'
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version,
            runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(), observations=observations), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    asyncio.run(main())
