import argparse
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
ARGS = None
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('workspace', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    ARGS = parser.parse_args()
sys.path.insert(0, str(ARGS.root.resolve() if ARGS else ROOT))
import dsh
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.subagent.acp import AcpProvider, CONFIG
from dsh.subprocess.local import LocalSubprocessRuntime


RAW = 'rollback leaked /private/path SECRET_TOKEN'
NAMES = ('published-post-exit', 'startup-post-exit', 'cancelled-startup-post-exit', 'throwing-error-sink')


def request(cwd, controller):
    return {'parent': SimpleNamespace(session=SimpleNamespace(header={'cwd': str(cwd)})),
        'signal': controller.signal, 'prompt': [{'type': 'text', 'text': 'explicit child task'}]}


async def wait_file(path):
    deadline = asyncio.get_running_loop().time() + 10
    while not path.exists():
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError('ACP teardown peer readiness not observed')
        await asyncio.sleep(0.01)


def failure(error):
    value = {'name': getattr(error, 'name', 'Error'), 'message': str(error)}
    if getattr(error, 'cause', None) is not None:
        value['cause'] = str(error.cause)
    if hasattr(error, 'errors'):
        value['errors'] = [failure(member) for member in error.errors]
    return value


async def observations(workspace):
    rows = []
    for name in NAMES:
        record = workspace / ('native-' + name + '.jsonl')
        controller, errors = AbortController(), []
        child, waits, terminations = None, 0, 0
        env = {'PROBE_RECORD': str(record)}
        if name != 'throwing-error-sink':
            env['PROBE_IGNORE_EOF'] = '1'
        if name == 'startup-post-exit':
            env['PROBE_MISSING_ID'] = '1'
        if name == 'cancelled-startup-post-exit':
            env.update(PROBE_NEW_READY=str(workspace / 'native-new-ready'), PROBE_NEW_GO=str(workspace / 'native-new-go'))
        if name == 'throwing-error-sink':
            env['PROBE_CRASH_AFTER_CHUNK'] = '1'
        ctx = Context()
        await ctx.plugin(LocalSubprocessRuntime)
        service = ctx.get('subprocess')
        spawn = service.spawn
        def terminate():
            nonlocal terminations
            terminations += 1
            child.terminate()
        async def wait_for_exit(signal=None):
            nonlocal waits
            waits += 1
            if signal is not None:
                return False
            await child.done
            raise RuntimeError(RAW)
        def capture(spec):
            nonlocal child
            child = spawn(spec)
            if name == 'throwing-error-sink':
                return child
            return SimpleNamespace(pid=child.pid, stdin=child.stdin, stdout=child.stdout,
                stderr=child.stderr, collected=child.collected, done=child.done,
                terminate=terminate, wait_for_exit=wait_for_exit)
        service.spawn = capture
        config = CONFIG({'command': sys.executable, 'args': [str(ROOT / 'scripts/oracles/subagent_acp_peer.py')],
            'env': env, 'disposeEofGraceMs': 30, 'disposeGraceMs': 30})
        backend = AcpProvider(ctx, config)
        def report(error, reason):
            errors.append(str(error))
            if name == 'throwing-error-sink':
                raise RuntimeError('diagnostic sink rejected')
        backend.report = report
        observed, run = {}, None
        async def dispose_failure():
            try:
                await run.dispose()
                return None
            except Exception as error:
                return error
        try:
            try:
                starting = asyncio.create_task(backend.start(request(workspace, controller)))
                if name == 'cancelled-startup-post-exit':
                    await wait_file(Path(env['PROBE_NEW_READY']))
                    controller.abort('startup cancellation')
                    Path(env['PROBE_NEW_GO']).write_text('go', encoding='utf-8')
                run = await starting
                observed['result'] = await run.result
                first, second = await dispose_failure(), await dispose_failure()
                observed['disposeFailure'] = None if first is None else failure(first)
                observed['sameDisposeFailure'] = first is second
            except Exception as error:
                observed['startFailure'] = failure(error)
            finally:
                if run is not None:
                    await dispose_failure()
            assert await child.wait_for_exit()
            observed.update(actualExit=(await child.done).exitCode, waits=waits, terminations=terminations,
                rawErrors=errors, listenerRemoved=not controller.signal._listeners,
                records=[json.loads(line) for line in record.read_text(encoding='utf-8').splitlines()])
            rows.append({'name': name, 'observed': observed})
        finally:
            await ctx.fiber.dispose()
    return rows


def public_observation(row):
    value = dict(row['observed'])
    value['wire'] = [{key: packet[key] for key in ('method', 'params', 'result') if key in packet}
        for packet in value.pop('records') if 'method' in packet or 'result' in packet]
    return {'name': row['name'], 'observed': value}


if __name__ == '__main__':
    report = {'observations': asyncio.run(observations(ARGS.workspace.resolve())),
        'root': str(ARGS.root.resolve()), 'module': str(Path(dsh.__file__).resolve()),
        'python': list(sys.version_info[:3])}
    ARGS.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
