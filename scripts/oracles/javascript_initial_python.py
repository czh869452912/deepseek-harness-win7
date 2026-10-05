import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace


async def observe(cancelled):
    from dsh.cordis.context import Context
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.subagent.runtime import SubagentRuntime
    from dsh.workflow.workflow_service import WorkflowEngine

    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    await ctx.plugin(SubagentRuntime)
    events, requests = [], []
    initial_held, release_initial = asyncio.Event(), asyncio.Event()
    spawned = []
    ready_messages = []
    initial_payloads = []
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*arguments, **options):
        process = await original_spawn(*arguments, **options)
        original_write, original_drain = process.stdin.write, process.stdin.drain
        original_read = process.stdout.readline

        def write(payload):
            initial_payloads.append(payload)
            initial_held.set()

        async def drain():
            await release_initial.wait()
            for payload in initial_payloads:
                original_write(payload)
            await original_drain()

        async def readline():
            line = await original_read()
            if line and json.loads(line)['type'] == 'ready':
                ready_messages.append(line)
            return line

        process.stdin.write, process.stdin.drain = write, drain
        process.stdout.readline = readline
        spawned.append(process)
        return process

    class Provider:
        name, inheritsParentContext = 'spawn', False
        capabilities = dict(agentOptions=True, outputSchema=True, depthLimit=False, toolFilter=False, persona=False)

        async def start(self, request):
            requests.append(request)
            raise ValueError('Unexpected child admission')

    ctx.get('subagents').registerProvider(Provider())
    await ctx.plugin(WorkflowEngine, dict(disposeGraceMs=5000, syncTimeoutMs=200))
    name = 'cancel-before-entry-exit' if cancelled else 'before-entry-exit'
    for kind in ('start', 'phase', 'log', 'agent-start', 'agent-end', 'end'):
        def received(info, value=None, kind=kind):
            event = dict(type=kind)
            if kind == 'end':
                event['outcome'] = copy.deepcopy(value)
            elif kind in ('agent-start', 'agent-end'):
                event['info'] = copy.deepcopy(value)
            elif kind in ('phase', 'log'):
                event['title' if kind == 'phase' else 'message'] = value
            events.append(event)
        ctx.on('workflow/' + kind, received)
    asyncio.create_subprocess_exec = spawn
    run = None
    try:
        run = ctx.get('workflowEngine').start(dict(meta=dict(name=name,
            description='actual entry blocked before Ready emission'),
            parent=SimpleNamespace(id='parent', options={}, ctx=ctx), script='phase("unreachable");return "unreachable"'))
        await asyncio.wait_for(initial_held.wait(), 5)
        workers = list(ctx.get('jsRuntime')._workers)
        assert len(workers) == 1 and len(spawned) == 1 and len(initial_payloads) == 1
        assert not workers[0].ready.done() and run._worker is None and not run._opening.done()
        if cancelled:
            run.cancel('')
        spawned[0].kill()
        await asyncio.wait_for(spawned[0].wait(), 5)
        release_initial.set()
        result = await asyncio.wait_for(asyncio.shield(run.result), 5)
        before = dict(entryBlocked=True, readyMessages=len(ready_messages), readyAdmitted=False,
            signalAborted=run.controller.signal.aborted)
        await run.dispose()
        return dict(name=name, result=result, events=events, requests=requests, before=before,
            exitCode=spawned[0].returncode, firstResultRetained=result is await run.result,
            goneAfterDispose=spawned[0].returncode is not None)
    finally:
        release_initial.set()
        asyncio.create_subprocess_exec = original_spawn
        if run is not None:
            await run.dispose()
        await ctx.fiber.dispose()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    if output.exists():
        raise ValueError('Fresh Native output required')
    sys.path.insert(0, str(root))
    observations = [await observe(cancelled) for cancelled in (False, True)]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version,
            modules=modules, assets={path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for directory in ('dsh/javascript/bin', 'dsh/javascript/workflow')
                for path in sorted((root / directory).iterdir()) if path.is_file()},
            observations=observations), stream, ensure_ascii=True, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    asyncio.run(main())
