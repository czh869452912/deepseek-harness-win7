"""Observe shared listing limits and sequential failure ownership."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CASES=[dict(limit=limit,failures=failures) for limit in (1,2,3) for failures in ([],['p0'],['p1'],['p2'],['d00'],['d01'],['d10'],['p1','d01'],['p2','d10'])]

async def observe():
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistence,CurrentJsonlSessionPersistencePlugin
    result=[]
    for row in CASES:
        backend=CurrentJsonlSessionPersistence('unused',format_version=4,list_concurrency=row['limit'])
        active=0;peak=0;completed=[];failures={name:ValueError(name) for name in row['failures']}
        async def read(name,value):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            try:
                await asyncio.sleep(0.008 if name in ('p0','d00') else 0.001)
                if name in failures:raise failures[name]
                return value
            finally:active-=1;completed.append(name)
        async def run(fn,*args):
            if fn==backend._projects:return await read('root',['p0','p1','p2'])
            if fn==backend._sessions:return await read(args[0],['d'+args[0][1]+str(i) for i in range(2)])
            raise AssertionError('unexpected filesystem call')
        backend._run=run
        async def task(directory):return await read(directory,directory)
        async def listing():
            try:return dict(values=await backend.mapSessionDirectories(task))
            except Exception as error:return dict(error=str(error),same=failures.get(str(error)) is error)
        values=await asyncio.gather(listing(),listing())
        result.append(dict(**row,peak=peak,active=active,completed=sorted(completed),values=values))
        await backend.close()
    configs=[]
    for value in (None,1,2.0,0,-1,1.5,True,'2'):
        config=dict(root='unused')
        if value is not None:config['listConcurrency']=value
        try:configs.append(dict(value=value,limit=CurrentJsonlSessionPersistencePlugin.Config(config)['listConcurrency']))
        except Exception:configs.append(dict(value=value,rejected=True))
    return result+[dict(configs=configs)]

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_listing.mts','Shared backend listing bound across simultaneous scans, all-settled completion, project-before-directory failure ownership and positive-integer configuration.',[Path(__file__).resolve(),ROOT/'dsh/session/jsonl_backend_current.py'])
