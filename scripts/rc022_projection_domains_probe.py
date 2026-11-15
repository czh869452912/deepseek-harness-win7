"""Run statistics/outline plugins against the explicit V4 registry."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CASES=ROOT/'scripts/oracles/session_stats_current_cases.json'

async def observe():
    from scripts.oracles.session_stats_current_python import execute
    from scripts.oracles.session_format_python import decode
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.session.stats_current import CurrentSessionStatsPlugin
    from dsh.session.turn_outline import SessionTurnOutlinePlugin
    rows=[dict(case=case['case'],value=execute(case,decode)) for case in json.loads(CASES.read_text(encoding='utf-8'))]
    for action in ('fresh','late','deferred-stats','deferred-outline'):
        ctx=Context()
        class Store(Plugin):
            def apply(self,owner):CurrentSessionStore(owner,4)
        class Registry(Plugin):
            def apply(self,owner):SessionProjectionRegistry(owner,4)
        try:
            await ctx.plugin(Store);await ctx.plugin(Registry)
            registry=ctx.get('sessionProjections');session=ctx.get('sessions').create('domains');row=dict(case=action)
            if action.startswith('deferred'):
                entered=asyncio.Event();release=asyncio.Event();original=registry.register
                async def delayed(definition):entered.set();await release.wait();return await original(definition)
                registry.register=delayed
                fiber=ctx.plugin(CurrentSessionStatsPlugin if action=='deferred-stats' else SessionTurnOutlinePlugin)
                await entered.wait();row['waiting']=fiber.state;row['before']=registry.snapshot(session);release.set();await fiber
                row['ready']=fiber.state;row['keys']=sorted(registry.snapshot(session)['values']);rows.append(row);continue
            async def mount():return await ctx.plugin(CurrentSessionStatsPlugin),await ctx.plugin(SessionTurnOutlinePlugin)
            fibers=await mount() if action=='fresh' else None
            for kind,data in [('turn/start',dict(turn=1)),('step/start',dict(turn=1,step=1)),('step/end',dict(turn=1,step=1)),('turn/end',dict(turn=1))]:session.append(kind,data)
            if fibers is None:fibers=await mount()
            row['summary']=registry.snapshot(session,registry.summaryKeys());row['full']=registry.snapshot(session);checkpoint=registry.checkpoint(session)
            row['cold']=registry.restore(checkpoint,[],session.seq,session.header,session.inheritedEventCount)['snapshot'];row['checkpointKeys']=sorted(checkpoint)
            await fibers[0].dispose();await fibers[1].dispose();row['released']=registry.snapshot(session);row['retainedKeys']=sorted(registry.checkpoint(session));await mount();row['remounted']=registry.snapshot(session);rows.append(row)
        finally:await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_projection_domains.mts','Actual statistics and turn-outline plugin readiness, V4 snapshots/checkpoints/cold replay, summary exclusion, disposal and remount; fresh Source rechecks existing statistics fold/schema corpus.',[Path(__file__).resolve(),CASES,ROOT/'dsh/session/stats_current.py',ROOT/'dsh/session/turn_outline.py',ROOT/'dsh/session/projections.py',*[ROOT/'scripts/oracles'/name for name in ('session_stats_current_python.py','session_stats_current_source.mts','session_format_python.py')]])
