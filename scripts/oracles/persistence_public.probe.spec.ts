import {it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import Sqlite from '@deepseek-ai/dsh-session-persistence-sqlite'
import {mkdtemp,rm,writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {execFileSync} from 'node:child_process'

it('observes numeric admission and cancellation at the actual physical read return',async()=>{
  const pin='cd5ef8148158c3a752a658978873241fdf8e2bbc'
  if(process.version!=='v22.22.2'||execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim()!==pin
    ||execFileSync('git',['-C','reference','status','--porcelain'],{encoding:'utf8'}).trim())throw new Error('Pinned clean Source required')
  const rows:any[]=[]
  for(const backend of ['jsonl-none','jsonl-zstd','sqlite']){
    for(const [operation,label,value] of [
      ['create','whole',1],['create','negative-zero',-0],['create','fraction',1.5],['create','boolean',true],
      ['append','whole',0],['append','negative-zero',-0],['append','fraction',0.5],['append','boolean',false],
      ['read','whole',0],['read','negative-zero',-0],['read','fraction',0.5],['read','boolean',false],
      ['read','unsafe',9007199254740992],['abort','before',0],['abort','after-read',0],
    ] as const){
      const root=await mkdtemp(join(tmpdir(),'dsh-public-read-'))
      const context=new Context(),name=backend+'/'+operation+'/'+label
      const meta:any={id:'s',version:0,createdAt:1}
      const event:any={type:'session/end-seed',seq:0,time:1,data:{}}
      const row:any={name}
      try{
        await context.plugin(SessionStore)
        if(backend==='sqlite')await context.plugin(Sqlite,{path:join(root,'store.db')})
        else await context.plugin(Jsonl,{root,compression:backend==='jsonl-zstd'?'zstd':'none'})
        const provider:any=context.sessionPersistence
        if(operation==='create')await provider.create({...meta,createdAt:value})
        else{
          await provider.create(meta)
          if(operation!=='append')await provider.append(meta.id,[event])
          if(operation==='append')await provider.append(meta.id,[{...event,seq:value}])
          else if(operation==='read')row.value=await provider.readFrom(meta.id,value)
          else{
            const owner=backend==='sqlite'?provider.store:provider
            const key=backend==='sqlite'?'loadStoredFrom':'loadStored'
            const original=owner[key].bind(owner)
            const controller=new AbortController()
            let received:any,release:any
            const entered=new Promise(resolve=>{received=resolve}),released=new Promise(resolve=>{release=resolve})
            const calls:any[]=[]
            owner[key]=async(...arguments_:any[])=>{
              calls.push({signalForwarded:arguments_[arguments_.length-1]===controller.signal})
              const result=await original(...arguments_)
              if(label==='after-read'){received();await released}
              return result
            }
            const reason=new Error('controlled read retired')
            if(label==='before')controller.abort(reason)
            const reading=provider.readFrom(meta.id,0,controller.signal)
            const settled=reading.then((result:any)=>({value:result}),error=>({error:{name:error.name,message:error.message},reasonIdentity:error===reason}))
            if(label==='after-read'){
              await entered
              controller.abort(reason)
              release()
            }
            Object.assign(row,await settled,{calls,aborted:controller.signal.aborted})
            owner[key]=original
          }
        }
        if(!row.error)row.accepted=true
      }catch(error:any){row.error={name:error.name,message:error.message};row.accepted=false}
      finally{await context.fiber.dispose();await rm(root,{recursive:true,force:true})}
      rows.push(row)
    }
  }
  await writeFile(process.env.DSH_PUBLIC_SOURCE_OUTPUT!,JSON.stringify({sourceCommit:pin,node:process.version,rows},null,2)+'\n',{flag:'wx'})
})
