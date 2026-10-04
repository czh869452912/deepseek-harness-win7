import asyncio
import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('workspace', type=Path)
parser.add_argument('trigger')
parser.add_argument('--root', type=Path, default=ROOT)
parser.add_argument('--peer', type=Path, default=ROOT / 'scripts/oracles/subprocess_tree_peer.py')
arguments = parser.parse_args()
ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))
import dsh
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.subprocess import LocalSubprocessRuntime, SubprocessCollect, SubprocessSpawnSpec, SubprocessStdio


async def prepare(workspace):
    context = Context()
    await context.plugin(LocalSubprocessRuntime)
    runtime = context.get('subprocess')
    controller = AbortController()
    handle = runtime.spawn(SubprocessSpawnSpec(
        argv=[sys.executable, str(arguments.peer.resolve()),
              'root', str(workspace / 'tree.json')], cwd=str(workspace),
        stdio=SubprocessStdio('ignore', SubprocessCollect(1024), SubprocessCollect(1024)),
        grace_ms=100, signal=controller.signal))
    while not (workspace / 'proceed').exists():
        await asyncio.sleep(0.01)
    return context, runtime, handle, controller


async def finish(context, handle, controller, trigger):
    if trigger == 'dispose':
        await context.fiber.dispose()
    else:
        if trigger == 'abort':
            controller.abort('explicit tree cancellation')
        else:
            handle.terminate()
        await handle.done
        await handle.wait_for_exit()
        await context.fiber.dispose()


if __name__ == '__main__':
    workspace = arguments.workspace.resolve()
    trigger = arguments.trigger
    (workspace / 'product.json').write_text(json.dumps({'root': str(ROOT),
        'module': str(Path(dsh.__file__).resolve()), 'python': list(sys.version_info[:3])}), encoding='utf-8')
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    context, runtime, handle, controller = loop.run_until_complete(prepare(workspace))
    if trigger in ('dispose', 'abort', 'terminate'):
        loop.run_until_complete(finish(context, handle, controller, trigger))
        sys.exit(0)
    if trigger == 'direct':
        sys.exit(23)
    raise RuntimeError('host-exit-uncaught-exception')
