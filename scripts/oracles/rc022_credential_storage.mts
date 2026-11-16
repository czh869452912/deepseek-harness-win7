import fs from 'node:fs/promises'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {LocalCredentialProvider}=await load('packages/credentials/credentials-local/src/index.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8'))
const directory=path.join(path.dirname(process.argv[3]!),'files/source'),rows:any[]=[]
await fs.mkdir(directory,{recursive:true})
for(const [index,text]of inputs.entries()){
 const filename=path.join(directory,index+'.yaml'),ctx=new Context(),events:string[]=[],states:any[]=[]
 if(text!==null)await fs.writeFile(filename,text,{mode:0o600})
 ctx.on('credentials/reference-updated',(key:string)=>events.push('ref:'+key))
 ctx.on('credentials/record-updated',(key:string)=>events.push('record:'+key))
 const errorText=(error:any)=>error.message.replaceAll(filename,'<file>')
 const snapshot=async(error:any=null)=>JSON.parse(JSON.stringify({error,exists:await fs.stat(filename).then(()=>true,()=>false),events:[...events],
  ref:await ctx.credentials.resolve('KEY')??null,info:await ctx.credentials.describe('KEY'),
  record:await ctx.credentials.readRecord('owner/a')??null,records:await ctx.credentials.listRecords()}))
 try{
  try{await ctx.plugin(LocalCredentialProvider,{path:filename,watch:false})}
  catch(error:any){rows.push({activation:errorText(error),exists:await fs.stat(filename).then(()=>true,()=>false)});continue}
  const service:any=ctx.credentials;states.push(await snapshot())
  const record={kind:'grant',payload:{count:1}}
  const operations=[()=>service.set('KEY','new'),()=>service.set('KEY','new'),()=>service.unset('ABSENT'),
   ()=>service.modifyRecord('owner/a',()=>record),()=>service.modifyRecord('owner/a',()=>undefined),
   ()=>service.set('KEY',''),()=>service.deleteRecord('owner/missing'),()=>service.unset('KEY'),()=>service.deleteRecord('owner/a')]
  for(const operation of operations){let error=null;try{await operation()}catch(failure:any){error=errorText(failure)}states.push(await snapshot(error))}
  const external='version: 1\nrefs: {KEY: external}\nrecords: {owner/a: {kind: grant, payload: {n: 2, x: true}}}\n'
  await fs.writeFile(filename,external);await service.enqueue(()=>service.refresh());states.push(await snapshot())
  await fs.writeFile(filename,'version: 2\nrefs: {KEY: secret}\n');await service.enqueue(()=>service.refresh());states.push(await snapshot())
  await fs.writeFile(filename,external);await service.set('OTHER','other');states.push(await snapshot())
  await fs.unlink(filename);await service.enqueue(()=>service.refresh());states.push(await snapshot())
  rows.push({activation:null,states})
 }finally{await ctx.fiber.dispose()}
}
{
 const ctx=new Context(),filename=path.join(directory,'drain.yaml')
 await ctx.plugin(LocalCredentialProvider,{path:filename,watch:false})
 const service:any=ctx.credentials,record={kind:'grant',payload:{durable:true}}
 let entered!:()=>void,release!:()=>void
 const waiting=new Promise<void>(resolve=>{entered=resolve}),gate=new Promise<void>(resolve=>{release=resolve})
 const first=service.modifyRecord('owner/a',async()=>{entered();await gate;return record})
 await waiting
 const queued=service.set('KEY','queued');let queuedError:any=null
 const queuedResult=queued.catch((error:any)=>{queuedError=error.message})
 let done=false
 const disposing=ctx.fiber.dispose().then(()=>{done=true})
 await new Promise(resolve=>setImmediate(resolve))
 const pending=!done;release()
 const result=await first;await queuedResult;await disposing
 let closedError:any=null;try{await service.unset('KEY')}catch(error:any){closedError=error.message}
 rows.push({drainPending:pending,sameObject:result===record&&await service.readRecord('owner/a')===record,
  queuedError,closedError,exists:await fs.stat(filename).then(()=>true,()=>false),refs:Object.fromEntries(service.values)})
}
{
 const ctx=new Context(),filename=path.join(directory,'watch.yaml'),events:string[]=[],waiters:any[]=[]
 ctx.on('credentials/reference-updated',(key:string)=>{const waiter=waiters.shift();if(waiter)waiter(key);else events.push(key)})
 await ctx.plugin(LocalCredentialProvider,{path:filename,watch:true,debounceMs:5})
 const observed:any[]=[]
 try{
  for(const value of ['created','changed',null]){
   if(value===null)await fs.unlink(filename)
   else await fs.writeFile(filename,'version: 1\nrefs: {KEY: '+value+'}\n',{mode:0o600})
   const event=events.length?events.shift():await new Promise<string>((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('watch observation timeout')),5000)
    waiters.push((key:string)=>{clearTimeout(timer);resolve(key)})
   })
   observed.push({event,value:await ctx.credentials.resolve('KEY')??null})
  }
 }finally{await ctx.fiber.dispose()}
 rows.push({watch:observed})
}
process.stdout.write(JSON.stringify(rows))
