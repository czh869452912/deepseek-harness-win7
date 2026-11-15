"""Compare policy-owned process cleanup against the fixed upstream provider."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.awaiting import start_coroutine
    from dsh.code_runtime.policy_processes import PolicyProcesses
    rows = []
    for action in ('policy', 'escalated', 'unpublished', 'no-store', 'unscoped',
                   'detached', 'retry', 'fanout', 'dispose'):
        ctx = Context()
        warnings = []
        ctx.logger.warn = lambda error: warnings.append(str(error))
        session = SimpleNamespace(id='session')
        mode = ['workspace-write']
        if action != 'no-store':
            ctx.set_service('sessions', SimpleNamespace(get=lambda key:
                session if key == session.id and action != 'unpublished' else None))
        ctx.set_service('sandboxPolicy', SimpleNamespace(resolve=lambda request: dict(mode=mode[0])))
        processes = PolicyProcesses(ctx)
        trace = []
        gate = asyncio.get_running_loop().create_future()
        calls = [0]
        failing = [action in ('retry', 'fanout')]
        async def release():
            calls[0] += 1
            trace.append('release')
            await asyncio.shield(gate)
            if failing[0]:
                raise RuntimeError('cleanup failed')
            trace.append('released')
        policy = dict(mode='danger-full-access' if action == 'escalated' else 'workspace-write',
                      workspaceRoot=str(ROOT))
        if action != 'unscoped':
            policy['sessionId'] = 'session'
        detach = processes.register(policy, release)
        if action == 'detached':
            detach()
            detach()
        def emit(identity, kind, value):
            ctx.emit('session/event', SimpleNamespace(id=identity), dict(type=kind, data=dict(mode=value)))
        row = dict(action=action)
        tasks = []
        try:
            emit('other', 'sandbox/mode', 'read-only')
            emit('session', 'turn/start', 'read-only')
            emit('session', 'sandbox/mode', 'workspace-write')
            row['unrelatedIgnored'] = calls[0] == 0
            if action == 'dispose':
                waiting = ctx.fiber.dispose()
                # Root disposal enters cleanup before its first suspension.
                for unused in range(8):
                    if calls[0]:
                        break
                    await asyncio.sleep(0)
            else:
                mode[0] = 'read-only'
                emit('session', 'sandbox/mode', mode[0])
                waiting = start_coroutine(processes.wait('session'))
            tasks.append(waiting)
            row['started'] = calls[0]
            emit('session', 'sandbox/mode', 'danger-full-access')
            row['sharedCleanup'] = calls[0] == row['started']
            if action == 'fanout':
                # A failure must not finish admission before every peer settles.
                async def peer():
                    trace.append('peer')
                    await asyncio.shield(peer_gate)
                    trace.append('peer-released')
                peer_gate = asyncio.get_running_loop().create_future()
                processes.register(dict(policy), peer)
                emit('session', 'sandbox/mode', 'workspace-write')
                both = start_coroutine(processes.wait('session'))
                tasks.append(both)
                gate.set_result(None)
                await asyncio.gather(waiting, return_exceptions=True)
                row['waitsForPeer'] = not both.done()
                peer_gate.set_result(None)
                waiting = both
            else:
                gate.set_result(None)
            try:
                await waiting
                row['result'] = 'done'
            except RuntimeError as error:
                row['result'] = str(error)
            if action in ('retry', 'fanout'):
                failing[0] = False
                await processes.wait('session')
                row['retryCount'] = calls[0]
            await processes.wait('other')
            await processes.wait()
            row['trace'] = list(trace)
            row['warnings'] = list(warnings)
            rows.append(row)
        finally:
            if not gate.done():
                gate.set_result(None)
            failing[0] = False
            await asyncio.gather(*tasks, return_exceptions=True)
            await ctx.fiber.dispose()
        row['finalCount'] = calls[0]
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_policy_processes.mts',
        'Eager policy invalidation, standing authority under one-shot escalation, unscoped/detached resources, shared cleanup, retry, all-settled admission and owner disposal.',
        [Path(__file__).resolve(), ROOT/'dsh/code_runtime/policy_processes.py'])
