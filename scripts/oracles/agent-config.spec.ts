import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import Llm from '@deepseek-ai/dsh-llm'
import Sessions from '@deepseek-ai/dsh-session'
import Tools from '@deepseek-ai/dsh-tools'
import Prompt from '@deepseek-ai/dsh-system-prompt'
import Agents from '@deepseek-ai/dsh-agent'
import Loop, { CONFIGURED_AGENT_IDENTITIES_KEY } from '@deepseek-ai/dsh-agent-loop'
import Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import { mkdtemp,rm,writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const wait=async(check:()=>unknown)=>{const end=Date.now()+3000;while(!check()){if(Date.now()>end)throw Error('timeout');await new Promise(r=>setTimeout(r,0))}}
it('observes configured identity and owned reload through real services',async()=>{
 const rows=[]
 for(const mode of ['identity','invalid','missing','reload','overlap','cancel','deferred']){
  const root=await mkdtemp(join(tmpdir(),'dsh-config-'));const ctx=new Context()
  let release=()=>{}
  try{
   await ctx.plugin(Llm);await ctx.plugin(Sessions);await ctx.plugin(Tools);await ctx.plugin(Prompt);await ctx.plugin(Agents)
   if(!['identity','invalid','deferred'].includes(mode))await ctx.plugin(Jsonl,{root,compression:'none'})
   if(mode==='identity'){
    ctx.provide(CONFIGURED_AGENT_IDENTITIES_KEY,{main:{id:'chosen',resume:false}} as any)
    await ctx.plugin(Loop,{agents:[{id:'main',sessionId:'ignored'},{id:'other',sessionId:'unchanged'}]} as any)
    rows.push({mode,chosen:!!ctx.agents.get('chosen' as any),unchanged:!!ctx.agents.get('unchanged' as any),ignored:!!ctx.agents.get('ignored' as any)})
   }else if(mode==='invalid'){
    let rejected=0
    for(const agents of [[{id:'a',sessionId:''}],[{id:'a',sessionId:'s',resumeSessionId:'r'}],[{id:'a',sessionId:'s'},{id:'b',sessionId:'s'}]]){
     try{await ctx.plugin(Loop,{agents} as any)}catch{rejected++}
    }
    rows.push({mode,rejected,published:ctx.agents.list().length})
   }else if(mode==='missing'){
    const failures:any[]=[];ctx.on('agent-loop/config-start-failed',v=>{failures.push(v)})
    await ctx.plugin(Loop,{agents:[{id:'a',resumeSessionId:'missing'}]} as any);await wait(()=>failures.length)
    rows.push({mode,failed:failures[0].sessionId,published:ctx.agents.list().length,stored:(await ctx.sessionPersistence.list()).length})
   }else if(mode==='deferred'){
    const fiber=await ctx.plugin(Loop,{agents:[{id:'a',resumeSessionId:'saved'}]} as any)
    const effect=fiber.getEffects().find(e=>e.label==='agentLoop.resume(a)')
    rows.push({mode,children:effect?.children.map(e=>e.label),published:ctx.agents.list().length})
   }else{
    const config={agents:[{id:'main',sessionId:'s',model:'mock'}]} as any
    const first=await ctx.plugin(Loop,config);await wait(()=>ctx.agents.get('s' as any));const old=ctx.agents.get('s' as any)!
    old.session.append('session/title',{title:'remember'} as any);await ctx.sessions.flush(old.session)
    let disposal:Promise<void>|undefined
    if(mode==='reload')await first.dispose()
    else{
     let entered=false;const gate=new Promise<void>(r=>{release=r})
     old.ctx.effect(()=>async()=>{entered=true;await gate})
     disposal=first.dispose();await wait(()=>entered)
    }
    const second=await ctx.plugin(Loop,config)
    if(mode==='cancel'){
     await second.dispose();release();await disposal
     rows.push({mode,published:ctx.agents.list().length})
    }else{
     let retained=true
     if(mode==='overlap'){await new Promise(r=>setTimeout(r,0));retained=ctx.agents.get('s' as any)===old;release();await disposal}
     await wait(()=>ctx.agents.get('s' as any));const current=ctx.agents.get('s' as any)!
     rows.push({mode,retained,replaced:current!==old,types:current.session.events.map(e=>e.type),history:current.session.events.some(e=>e.type==='session/title' && (e.data as any).title==='remember')})
     await second.dispose()
    }
   }
  }finally{release();await ctx.fiber.dispose();await rm(root,{recursive:true,force:true})}
 }
 await writeFile(process.env.AGENT_CONFIG_OUTPUT!,JSON.stringify(rows,null,2))
})
