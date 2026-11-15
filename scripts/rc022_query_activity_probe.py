"""Direct current query activity observers receive the same controlled trace."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CASES=ROOT/'tests/fixtures/rc022_query_activity.json'


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.sdk.query_activity import QueryActivity
    rows=[]
    for case in json.loads(CASES.read_text(encoding='utf-8')):
        ctx=Context();signal=AbortController();notifications=[];closed=[];own=[True];idle=asyncio.get_event_loop().create_future()
        async def when_idle():await idle
        agent=NS(session=NS(id='root'),status='running',whenIdle=when_idle)
        ctx.set_service('goals',NS(get=lambda _:dict(phase='active')))
        activity=QueryActivity(ctx,agent,NS(notify=lambda method,params:notifications.append(dict(method=method,params=params))),lambda:own[0],signal.signal,lambda _:closed.append(True))
        try:
            for action in case['actions']:
                method=action[0];value=action[1] if len(action)>1 else None
                if method=='accept':activity.accept(value)
                elif method=='event':ctx.emit('session/event',agent.session,value)
                elif method=='foreign':ctx.emit('session/event',NS(id='other'),value)
                elif method=='own':own[0]=value
                elif method=='status':agent.status=value;ctx.emit('agent/status',dict(agent=agent,status=value))
                elif method=='activation':ctx.emit('goal/activation-changed',value)
                elif method=='unload':activity.goalUnavailable()
                elif method=='dispose':ctx.emit('agent/disposed',dict(agent=agent))
                elif method=='error':ctx.emit('agent/error',dict(agent=agent,error=RuntimeError('failed')))
                elif method=='abort':signal.abort(RuntimeError('stop'))
                elif method=='idle':agent.status='idle';idle.set_result(None);await asyncio.sleep(0);await asyncio.sleep(0)
            rows.append(dict(name=case['name'],notifications=notifications,closed=activity.closed,closeCount=len(closed)))
        finally:
            activity.close()
            if not idle.done():idle.set_result(None)
            await asyncio.gather(*list(activity.tasks),return_exceptions=True)
            await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_query_activity.mts','Actual query activity observers receive controlled own/foreign event traces for acknowledgment, command errors, admitted input, nested identities, first goal terminal, disarm/provider withdrawal, Agent disposal, failure and lifetime abort. No model or full goal scheduler qualification.',[Path(__file__).resolve(),CASES,ROOT/'dsh/sdk/query_activity.py'],prepare=lambda output:[CASES])
