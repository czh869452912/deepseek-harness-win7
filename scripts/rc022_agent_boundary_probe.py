"""Observe Agent-owned turn boundaries independently of loop mounting."""
import asyncio
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.session.current_session import CurrentSessionStore,CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    rows=[]
    for action in ('detached','live','replacement','deferred'):
        ctx=Context()
        class Store(Plugin):
            def apply(self,owner):CurrentSessionStore(owner,4)
        class Registry(Plugin):
            def apply(self,owner):SessionProjectionRegistry(owner,4)
        try:
            await ctx.plugin(Store);await ctx.plugin(Registry);projections=ctx.get('sessionProjections');row=dict(action=action)
            if action=='deferred':
                entered=asyncio.Event();release=asyncio.Event();original=projections.register
                async def delayed(definition):entered.set();await release.wait();return await original(definition)
                projections.register=delayed;fiber=ctx.plugin(CurrentAgentPlugin);await entered.wait();row['waiting']=fiber.state;release.set();await fiber;row['ready']=fiber.state;rows.append(row);continue
            fiber=await ctx.plugin(CurrentAgentPlugin);agents=ctx.get('agents')
            session=CurrentSession.create('boundary',format_version=4) if action=='detached' else ctx.get('sessions').create('boundary')
            row['initial']=agents.turnBoundaryOf(session);session.append('turn/start',dict(turn=3));session.append('step/start',dict(turn=3,step=1));row['open']=agents.turnBoundaryOf(session)
            session.append('step/end',dict(turn=3,step=1));session.append('turn/end',dict(turn=3));row['closed']=agents.turnBoundaryOf(session);row['checkpoint']=projections.checkpoint(session)
            await fiber.dispose();session.append('turn/start',dict(turn=4));row['released']=projections.checkpoint(session);row['unread']=projections.checkpoint(CurrentSession.create('unread',format_version=4));row['retained']=agents.turnBoundaryOf(session)
            if action=='replacement':
                await ctx.plugin(CurrentAgentPlugin);row['replacement']=ctx.get('agents').turnBoundaryOf(session);row['newCheckpoint']=projections.checkpoint(session)
            rows.append(row)
        finally:await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_agent_boundary.mts','Agent registry owns its awaited turn-boundary handle without a loop; exact live/detached Session positions, released checkpoints/readers and replacement.',[Path(__file__).resolve(),ROOT/'dsh/core/agent_current.py',ROOT/'dsh/core/turn_boundary.py',ROOT/'dsh/core/agent_loop.py',ROOT/'dsh/core/react_loop_current.py'])
