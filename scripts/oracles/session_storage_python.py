import asyncio,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from dsh.cordis.context import Context
from dsh.core.session import SessionPlugin,SessionHeader
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
MODES=['lazy','duplicate','cursor','legacy','unknown','cold-adopt','materialize','invalid-read']
def event(seq=0,kind='session/end-seed',data=None):return dict(seq=seq,type=kind,time=seq+1,data={} if data is None else data)
async def observe():
 rows=[]
 for mode in MODES:
  with tempfile.TemporaryDirectory() as root:
   ctx=Context()
   async def mount():
    await ctx.plugin(SessionPlugin);await ctx.plugin(JsonlSessionPersistencePlugin,{'root':root});return ctx.get('sessionPersistence')
   try:
    p=await mount();meta=SessionHeader('s',created_at=1);await p.create(meta)
    if mode=='lazy':
     meta.created_at=20;before=len(await p.list());await p.append('s',[event()]);rows.append(dict(mode=mode,before=before,createdAt=(await p.read_from('s',0)).meta.created_at))
    elif mode=='duplicate':
     rejected=False
     try:await p.create(SessionHeader('s',cwd=root))
     except ValueError:rejected=True
     rows.append(dict(mode=mode,rejected=rejected,physical=len(await p.list())))
    elif mode=='cursor':
     rejected=0
     for events in [[event(1)],[event(),event(2)]]:
      try:await p.append('s',events)
      except ValueError:rejected+=1
     await p.append('s',[event()])
     try:await p.append('s',[event()])
     except ValueError:rejected+=1
     rows.append(dict(mode=mode,rejected=rejected,seqs=[e['seq'] for e in (await p.read_from('s',0)).events]))
    elif mode=='legacy':
     rejected=0
     for ev in [event(0,'mode/set'),event(0,'request/header-delta'),event(0,'request/header',{'reason':'fallback'})]:
      try:await p.append('s',[ev])
      except ValueError:rejected+=1
     rows.append(dict(mode=mode,rejected=rejected,physical=len(await p.list())))
    elif mode=='unknown':
     await p.append('s',[event(0,'future/plugin')]);rejected=0
     for read in [lambda:p.inspect('s'),lambda:p.load('s'),lambda:p.read_from('s',0)]:
      try:await read()
      except ValueError:rejected+=1
     rows.append(dict(mode=mode,rejected=rejected,physical=len(await p.list())))
    elif mode=='cold-adopt':
     await p.append('s',[event(0,'turn/start',{'turn':1})]);await ctx.fiber.dispose();ctx=Context();p=await mount()
     await p.append('s',[event(2)]);rows.append(dict(mode=mode,types=[e['type'] for e in (await p.read_from('s',0)).events]))
    elif mode=='materialize':
     s=ctx.get('sessions').create('live');await p.ensure_materialized(s);await p.ensure_materialized(s);rows.append(dict(mode=mode,events=len((await p.read_from(s.id,0)).events)))
    else:
     ev=event(0,'turn/start',{'turn':1});ev['time']='bad';await p.append('s',[ev]);rejected=0
     for read in [lambda:p.inspect('s'),lambda:p.load('s')]:
      try:await read()
      except ValueError:rejected+=1
     rows.append(dict(mode=mode,rejected=rejected,physical=len((await p.read_from('s',0)).events)))
   finally:await ctx.fiber.dispose()
 return rows
if __name__=='__main__':Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()),indent=2)+'\n',encoding='utf-8')
