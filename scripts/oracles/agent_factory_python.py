"""Observation-only Python half of the source-derived Agent factory probes."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.cordis import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin, SessionPreparation
from dsh.core.abort import AbortController


async def main():
    rows = []
    for mode in ['success', 'reject', 'commit', 'caller-load', 'owner-load', 'factory-load',
                 'caller-setup', 'owner-setup', 'factory-setup']:
        ctx = Context()
        SessionPlugin().apply(ctx)
        AgentPlugin().apply(ctx)
        AgentLoopPlugin().apply(ctx)
        owner = ctx.plugin(lambda scope: None)
        await owner
        signal = AbortController()
        session = ctx.get('sessions').prepare('probe')
        reached, late = asyncio.Event(), asyncio.Event()
        counters = {'releases': 0, 'committed': 0}
        events = []
        for name in ['session/created', 'agent/created', 'agent/session-start']:
            ctx.on(name, lambda *args, name=name: events.append(name))
        def release():
            counters['releases'] += 1
        async def prepare(sid, signal):
            if mode.endswith('-load'):
                reached.set()
                await late.wait()
            return SessionPreparation.create(session, release)
        ctx.set_service('session_persistence', SimpleNamespace(prepare=prepare))
        def commit():
            if mode == 'commit':
                raise RuntimeError('commit failed')
            counters['committed'] += 1
        async def setup(scope):
            if not mode.endswith('-load'):
                reached.set()
                await late.wait()
            if mode == 'reject':
                raise RuntimeError('setup failed')
            return SimpleNamespace(commit=commit)
        job = asyncio.create_task(owner.ctx.get('agents').resume({
            'resumeSessionId': 'probe', 'signal': signal.signal, 'setup': setup}))
        await reached.wait()
        before = {'session': ctx.get('sessions').get('probe') is not None,
                  'agent': ctx.get('agents').get('probe') is not None, 'events': list(events)}
        if mode.startswith('caller-'):
            signal.abort(RuntimeError('cancelled'))
        elif mode.startswith('owner-'):
            await owner.dispose()
        elif mode.startswith('factory-'):
            await ctx.get('agent_loop').teardown()
        else:
            late.set()
        handle = None
        try:
            handle = await job
        except RuntimeError:
            pass
        late.set()
        await asyncio.sleep(0.01)
        after = {'rejected': handle is None, 'exact': handle is not None and handle.agent.session is session,
                 'events': list(events), **counters}
        if handle:
            await handle.dispose()
        clean = ctx.get('sessions').get('probe') is None and ctx.get('agents').get('probe') is None
        await ctx.fiber.dispose()
        rows.append({'mode': mode, 'before': before, 'after': after, 'clean': clean})
    Path(sys.argv[1]).write_text(json.dumps(rows, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
