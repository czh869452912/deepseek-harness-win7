import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
it('observes reserved Session identities through the real persistence service', async () => {
 const rows=[]
 for(const mode of ['reuse','mutated-release','reserved-write','cancel-wait','revision']) {
  const root=await mkdtemp(join(tmpdir(),'dsh-prepared-'));const ctx=new Context()
  try {
   await ctx.plugin(SessionStore);await ctx.plugin(Jsonl,{root,compression:'none'})
   const p=ctx.sessionPersistence;const sid='s' as any
   await p.create({id:sid,version:0,createdAt:1,delegationDepth:0})
   await p.append(sid,[{type:'turn/start',seq:0,time:1,data:{turn:1}},{type:'turn/end',seq:1,time:2,data:{turn:1,reason:{kind:'completed'}}}])
   if(mode==='revision'){
    await p.inspect(sid)
    await p.append(sid,[{type:'turn/start',seq:2,time:3,data:{turn:2}}])
    const held=await p.prepare(sid)
    rows.push({mode,types:held.session.events.map(e=>e.type),physical:(await p.readFrom(sid,0)).events.map(e=>e.type)})
    held[Symbol.dispose]();continue
   }
   const first=await p.prepare(sid);const exact=first.session
   if(mode==='reserved-write'){
    let rejected=false
    try {await p.append(sid,[{type:'turn/start',seq:2,time:3,data:{turn:2}}])}catch{rejected=true}
    rows.push({mode,rejected,physical:(await p.readFrom(sid,0)).events.length})
    first[Symbol.dispose]();continue
   }
   if(mode==='cancel-wait'){
    const controller=new AbortController();const reason=new Error('cancel observer')
    const waiting=p.prepare(sid,controller.signal).then(()=>false,e=>e===reason)
    controller.abort(reason)
    const cancelled=await waiting
    first[Symbol.dispose]();const second=await p.prepare(sid)
    rows.push({mode,cancelled,same:second.session===exact});second[Symbol.dispose]();continue
   }
   if(mode==='mutated-release')exact.append('turn/start',{turn:2})
   first[Symbol.dispose]();const second=await p.prepare(sid)
   rows.push({mode,same:second.session===exact,types:second.session.events.map(e=>e.type)})
   second[Symbol.dispose]()
  }finally{await ctx.fiber.dispose();await rm(root,{recursive:true,force:true})}
 }
 await writeFile(process.env.SESSION_PREPARED_OUTPUT!,JSON.stringify(rows,null,2))
})
