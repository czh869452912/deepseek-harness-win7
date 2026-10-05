import {it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import Sqlite from '@deepseek-ai/dsh-session-persistence-sqlite'
import {mkdtemp,rm,writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {execFileSync} from 'node:child_process'

it('observes queued cancellation, legacy prefix forwarding and SQLite aborted failure priority',async()=>{
  const pin='cd5ef8148158c3a752a658978873241fdf8e2bbc'
  if(process.version!=='v22.22.2'||execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim()!==pin
    ||execFileSync('git',['-C','reference','status','--porcelain'],{encoding:'utf8'}).trim())throw new Error('Pinned clean Source required')
  const rows:any[]=[]
  for(const name of ['jsonl-none/queued','jsonl-zstd/queued','sqlite/queued','sqlite/legacy-forward','sqlite/legacy-after','sqlite/aborted-failure']){
    const root=await mkdtemp(join(tmpdir(),'dsh-read-order-')),context=new Context()
    const row:any={name},controller=new AbortController(),reason=new Error('controlled read retired')
    let enter:any,release:any
    const entered=new Promise(resolve=>{enter=resolve}),released=new Promise(resolve=>{release=resolve})
    try{
      await context.plugin(SessionStore)
      if(name.startsWith('sqlite'))await context.plugin(Sqlite,{path:join(root,'store.db')})
      else await context.plugin(Jsonl,{root,compression:name.startsWith('jsonl-zstd')?'zstd':'none'})
      const provider:any=context.sessionPersistence,legacy=name.includes('legacy')
      await provider.create({id:'s',version:0,createdAt:1})
      await provider.append('s',[{type:legacy?'user/message':'session/end-seed',seq:0,time:1,
        data:legacy?{content:[{type:'text',text:'legacy'}],source:{kind:'user'}}:{}}])
      const owner=name.startsWith('sqlite')?provider.store:provider
      const key=legacy||!name.startsWith('sqlite')?'loadStored':'loadStoredFrom',original=owner[key].bind(owner)
      const calls:any[]=[]
      owner[key]=async(...arguments_:any[])=>{
        calls.push({signalForwarded:arguments_[arguments_.length-1]===controller.signal})
        const value=await original(...arguments_)
        if(name.endsWith('aborted-failure')){controller.abort(reason);throw new Error('controlled read failure')}
        if(name.endsWith('queued')&&calls.length===1||name.endsWith('legacy-after')){enter();await released}
        return value
      }
      const settle=(promise:Promise<any>)=>promise.then(value=>({value}),error=>({error:{name:error.name,message:error.message},reasonIdentity:error===reason}))
      if(name.endsWith('queued')){
        const first=settle(provider.readFrom('s',0))
        await entered
        let enqueued:any
        const queued=new Promise(resolve=>{enqueued=resolve})
        const originalSerialize=provider.coordinator.serialize.bind(provider.coordinator)
        provider.coordinator.serialize=(...arguments_:any[])=>{enqueued();return originalSerialize(...arguments_)}
        const second=settle(provider.readFrom('s',0,controller.signal))
        await queued
        controller.abort(reason)
        let timer:any
        const early:any=await Promise.race([second,new Promise(resolve=>{timer=setTimeout(()=>resolve({pending:true}),1000)})])
        clearTimeout(timer)
        row.settledBeforeRelease=!early.pending
        row.callsBeforeRelease=calls.length
        release()
        row.first=await first
        Object.assign(row,await second)
        provider.coordinator.serialize=originalSerialize
      }else{
        const reading=settle(provider.readFrom('s',0,controller.signal))
        if(name.endsWith('legacy-after')){await entered;controller.abort(reason);release()}
        Object.assign(row,await reading)
      }
      row.calls=calls
      row.aborted=controller.signal.aborted
      owner[key]=original
    }finally{release();await context.fiber.dispose();await rm(root,{recursive:true,force:true})}
    rows.push(row)
  }
  await writeFile(process.env.DSH_ORDER_SOURCE_OUTPUT!,JSON.stringify({sourceCommit:pin,node:process.version,rows},null,2)+'\n',{flag:'wx'})
})
