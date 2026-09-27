import asyncio,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dsh.cordis.context import Context
from dsh.core.session import SessionPlugin,SessionHeader
from dsh.core.abort import AbortController
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
async def observe():
 rows=[]
 for mode in ['reuse','mutated-release','reserved-write','cancel-wait','revision']:
  with tempfile.TemporaryDirectory() as root:
   ctx=Context()
   try:
    await ctx.plugin(SessionPlugin);await ctx.plugin(JsonlSessionPersistencePlugin,{'root':root})
    p=ctx.get('sessionPersistence');sid='s'
    await p.create(SessionHeader.from_dict(dict(id=sid,version=0,createdAt=1,delegationDepth=0)))
    await p.append(sid,[dict(type='turn/start',seq=0,time=1,data=dict(turn=1)),dict(type='turn/end',seq=1,time=2,data=dict(turn=1,reason=dict(kind='completed')))])
    if mode=='revision':
     await p.inspect(sid);await p.append(sid,[dict(type='turn/start',seq=2,time=3,data=dict(turn=2))])
     held=await p.prepare(sid)
     rows.append(dict(mode=mode,types=[e['type'] for e in held.session.events],physical=[e['type'] for e in (await p.read_from(sid,0)).events]));held.dispose();continue
    first=await p.prepare(sid);exact=first.session
    if mode=='reserved-write':
     rejected=False
     try:await p.append(sid,[dict(type='turn/start',seq=2,time=3,data=dict(turn=2))])
     except ValueError:rejected=True
     rows.append(dict(mode=mode,rejected=rejected,physical=len((await p.read_from(sid,0)).events)));first.dispose();continue
    if mode=='cancel-wait':
     controller=AbortController();reason=ValueError('cancel observer')
     waiting=asyncio.create_task(p.prepare(sid,controller.signal));controller.abort(reason)
     cancelled=False
     try:await waiting
     except ValueError as error:cancelled=error is reason
     first.dispose();second=await p.prepare(sid)
     rows.append(dict(mode=mode,cancelled=cancelled,same=second.session is exact));second.dispose();continue
    if mode=='mutated-release':exact.append('turn/start',{'turn':2})
    first.dispose();second=await p.prepare(sid)
    rows.append(dict(mode=mode,same=second.session is exact,types=[e['type'] for e in second.session.events]));second.dispose()
   finally:await ctx.fiber.dispose()
 return rows
if __name__=='__main__':Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()),indent=2)+'\n',encoding='utf-8')
