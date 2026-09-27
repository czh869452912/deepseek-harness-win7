import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
it('observes real live JSONL lifecycle', async () => {
  const rows=[]
  for (const mode of ['unload','preexisting','reload-open','collision']) {
    const root=await mkdtemp(join(tmpdir(),'dsh-live-'))
    let ctx=new Context()
    const turn=(s:any,n=1)=>{s.append('turn/start',{turn:n});s.append('turn/end',{turn:n,reason:{kind:'completed'}})}
    try {
      await ctx.plugin(SessionStore)
      let session:any
      if(mode==='preexisting'){session=ctx.sessions.create('s' as any);turn(session)}
      let fiber=await ctx.plugin(Jsonl,{root,compression:'none'})
      if(!session) session=ctx.sessions.create('s' as any)
      if(mode==='reload-open') session.append('turn/start',{turn:1})
      else if(mode!=='preexisting') turn(session)
      if(mode==='unload'||mode==='reload-open'){
        await fiber.dispose()
        fiber=await ctx.plugin(Jsonl,{root,compression:'none'})
      }
      if(mode==='reload-open') session.append('turn/end',{turn:1,reason:{kind:'completed'}})
      await ctx.sessions.flush(session)
      await ctx.sessions.flush(session)
      let rejected=false
      if(mode==='collision'){
        await ctx.fiber.dispose()
        ctx=new Context();await ctx.plugin(SessionStore);await ctx.plugin(Jsonl,{root,compression:'none'})
        session=ctx.sessions.create('s' as any);turn(session,2)
        try {await ctx.sessions.flush(session)} catch {rejected=true}
      }
      const physical=await ctx.sessionPersistence.readFrom('s' as any,0)
      rows.push({mode,rejected,events:physical.events.map(e=>({type:e.type,seq:e.seq,data:e.data}))})
    }finally{await ctx.fiber.dispose();await rm(root,{recursive:true,force:true})}
  }
  await writeFile(process.env.SESSION_LIVE_OUTPUT!,JSON.stringify(rows,null,2))
})
