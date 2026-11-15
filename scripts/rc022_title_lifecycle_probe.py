"""Compare cancellation and teardown of V4 title-provider work."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_title_probe import CONFIG,message

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.cordis.awaiting import start_coroutine
    from dsh.core.abort import AbortController
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.session.current_session import CurrentSessionStore,CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.session.canonical_title import SessionTitleService
    from dsh.core.session.json import UNDEFINED
    rows=[]
    with patch.object(CurrentSession,'_event_time',return_value=1000):
        for action in ('overlap','caller-cancel','session-detach','service-drain','queued-dispose','empty-fallback'):
            ctx=Context();releases=[];pending=[]
            class Store(Plugin):
                def apply(self,owner):CurrentSessionStore(owner,4)
            class Registry(Plugin):
                def apply(self,owner):SessionProjectionRegistry(owner,4)
            try:
                await ctx.plugin(Store);await ctx.plugin(Registry);await ctx.plugin(CurrentAgentPlugin)
                fiber=await ctx.plugin(SessionTitleService,dict(CONFIG,fallbackMaxBytes=1) if action=='empty-fallback' else CONFIG)
                titles=ctx.get('sessionTitle');store=ctx.get('sessions');session=store.prepare('lifecycle');detach=store.enter(session);store.announce(session)
                session.append('user/message',message('中文' if action=='empty-fallback' else 'A human prompt'),'append');row=dict(action=action)
                if action=='queued-dispose':
                    job=start_coroutine(titles.refresh(session));pending.append(job);closing=fiber.dispose()
                    try:await job
                    except Exception as error:row['error']=str(error)
                    await closing;row['title']=titles.get(session)
                else:
                    await titles.refresh(session);requests=[];entered=asyncio.Event();release=asyncio.Event();releases.append(release);signals=[]
                    async def generate(request):
                        index=len(requests);requests.append(dict(messages=request['messages'],currentTitle=request.get('currentTitle')));signals.append(request['signal']);entered.set()
                        if index==0:await release.wait()
                        return dict(title='Older' if index==0 else 'Newer',messageSeqs=[request['messages'][0]['seq']])
                    titles.register(dict(id='provider',automatic='first-prompt',generate=generate))
                    controller=AbortController();primary=RuntimeError('caller cancelled')
                    job=start_coroutine(titles.refresh(session,controller.signal if action=='caller-cancel' else None));pending.append(job);await asyncio.wait_for(entered.wait(),2)
                    if action=='overlap':row['new']=await titles.refresh(session)
                    elif action=='caller-cancel':controller.abort(primary)
                    elif action=='session-detach':detach()
                    elif action=='service-drain':
                        closing=asyncio.ensure_future(fiber.dispose());await signals[0].wait_aborted();row['draining']=not closing.done()
                    row['aborted']=signals[0].aborted;release.set()
                    try:row['result']=await job
                    except Exception as error:
                        row['error']=str(error)
                        if action=='caller-cancel':row['sameReason']=error is primary
                    if action=='service-drain':await closing
                    row['requests']=requests;row['title']=titles.get(session)
                if action not in ('service-drain','queued-dispose'):await fiber.dispose()
                row['released']=[ctx.get('sessionProjections').stateOf(session,key) is not UNDEFINED for key in ('title','titleInput')]
                row['titleEvents']=[event['data'] for event in session.snapshotEvents() if event['type']=='session/title']
                rows.append(row)
            finally:
                for release in releases:release.set()
                if pending:await asyncio.gather(*pending,return_exceptions=True)
                await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_title_lifecycle.mts','Title refresh overlap, exact caller abort reason, Session detachment, queued fallback/service unload, drain barriers and underivable fallback.',[Path(__file__).resolve(),ROOT/'scripts/rc022_title_probe.py',ROOT/'dsh/session/canonical_title.py',ROOT/'dsh/core/session/session.py'])
