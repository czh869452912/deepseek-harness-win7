import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const modes=['lazy','duplicate','cursor','legacy','unknown','cold-adopt','materialize','invalid-read']
it('observes the public storage boundary through real JSONL services',async()=>{
 const rows=[]
 for(const mode of modes){
  const root=await mkdtemp(join(tmpdir(),'dsh-storage-'));let ctx=new Context()
  const mount=async()=>{await ctx.plugin(SessionStore);await ctx.plugin(Jsonl,{root,compression:'none'});return ctx.sessionPersistence}
  const event=(seq=0,type='session/end-seed',data={})=>({seq,type,time:seq+1,data}) as any
  const meta={id:'s' as any,version:0 as const,createdAt:1}
  try{
   let p=await mount();await p.create(meta)
   if(mode==='lazy'){
    meta.createdAt=20;const before=(await p.list()).length;await p.append(meta.id,[event()])
    rows.push({mode,before,createdAt:(await p.readFrom(meta.id,0)).meta.createdAt})
   }else if(mode==='duplicate'){
    let rejected=false;try{await p.create({...meta,cwd:root})}catch{rejected=true}
    rows.push({mode,rejected,physical:(await p.list()).length})
   }else if(mode==='cursor'){
    let rejected=0;for(const events of [[event(1)],[event(),event(2)]]){try{await p.append(meta.id,events)}catch{rejected++}}
    await p.append(meta.id,[event()]);try{await p.append(meta.id,[event()])}catch{rejected++}
    rows.push({mode,rejected,seqs:(await p.readFrom(meta.id,0)).events.map(e=>e.seq)})
   }else if(mode==='legacy'){
    let rejected=0;for(const ev of [event(0,'mode/set'),event(0,'request/header-delta'),event(0,'request/header',{reason:'fallback'})]){try{await p.append(meta.id,[ev])}catch{rejected++}}
    rows.push({mode,rejected,physical:(await p.list()).length})
   }else if(mode==='unknown'){
    await p.append(meta.id,[event(0,'future/plugin')]);let rejected=0
    for(const read of [()=>p.inspect(meta.id),()=>p.load(meta.id),()=>p.readFrom(meta.id,0)]){try{await read()}catch{rejected++}}
    rows.push({mode,rejected,physical:(await p.list()).length})
   }else if(mode==='cold-adopt'){
    await p.append(meta.id,[event(0,'turn/start',{turn:1})]);await ctx.fiber.dispose();ctx=new Context();p=await mount()
    await p.append(meta.id,[event(2)])
    rows.push({mode,types:(await p.readFrom(meta.id,0)).events.map(e=>e.type)})
   }else if(mode==='materialize'){
    const s=ctx.sessions.create('live' as any);await p.ensureMaterialized(s);await p.ensureMaterialized(s)
    rows.push({mode,events:(await p.readFrom(s.id,0)).events.length})
   }else{
    await p.append(meta.id,[{...event(0,'turn/start',{turn:1}),time:'bad'} as any]);let rejected=0
    for(const read of [()=>p.inspect(meta.id),()=>p.load(meta.id)]){try{await read()}catch{rejected++}}
    rows.push({mode,rejected,physical:(await p.readFrom(meta.id,0)).events.length})
   }
  }finally{await ctx.fiber.dispose();await rm(root,{recursive:true,force:true})}
 }
 await writeFile(process.env.SESSION_STORAGE_OUTPUT!,JSON.stringify(rows,null,2))
})
