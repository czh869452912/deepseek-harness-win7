import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { load } from './rc022_subagent_fixture.mts'
const api=await load('packages/sdk/client/src/api.ts'),workspace=JSON.parse(readFileSync(process.argv[3],'utf8')),source=process.argv[2]
async function scenario(kind:string){
 const directory=join(workspace,'source',kind);mkdirSync(directory,{recursive:true})
 const ready=join(directory,'ready'),go=join(directory,'go'),record=join(directory,'record'),startup=kind.startsWith('start')
 const env={...process.env,FAKE_RECORD_INIT:record,...startup?{FAKE_INIT_READY:ready,FAKE_INIT_GO:go}:{FAKE_IGNORE_EOF:'1'},...kind==='start-failure'?{FAKE_INIT_ERROR_ONCE_FILE:join(directory,'failed')}:{}}
 const runtime={command:process.execPath,args:[join(source,'packages/sdk/client/tests/fake-runtime.ts')],cwd:directory,environment:()=>env,description:'SDK owner fixture',initializeTimeoutMs:3000,requestTimeoutMs:3000,shutdownTimeoutMs:100,disposeEofGraceMs:100,disposeGraceMs:500}
 const harness=api.createProcessDeepSeekHarness(runtime,{cwd:directory,provider:'script',model:'model'}),original=harness.client,clients=[original]
 try{
  let shared:Promise<any>,same:boolean
  if(startup){shared=harness.start();same=shared===harness.start();const deadline=Date.now()+5000;while(!existsSync(ready)){if(Date.now()>deadline)throw Error('ready timeout');await new Promise(r=>setTimeout(r,5))}}
  else{await harness.start();shared=harness.close();same=shared===harness.close()}
  let settled=false,secondSettled=false;shared.then(()=>{settled=true},()=>{settled=true})
  const abandoned=Promise.withResolvers<void>(),one=Promise.race([shared,abandoned.promise]),two=shared.then(value=>{secondSettled=true;return value},error=>{secondSettled=true;throw error})
  if(kind.endsWith('timeout'))await new Promise(r=>setTimeout(r,10))
  abandoned.resolve();await one
  const pending=!settled&&!secondSettled,live=original.child.exitCode===null&&original.child.signalCode===null
  writeFileSync(go,'release');let failure:string|null=null
  try{await two}catch(error:any){failure=error.name}
  const swapped=harness.client!==original
  if(swapped){clients.push(harness.client);await harness.start()}
  const handshakes=readFileSync(record,'utf8').trim().split('\n').length
  await harness.close()
  return {kind,sameHandle:same,pending,liveAtAbandonment:live,failure,swapped,handshakes,
   reaped:clients.every(client=>client.child.exitCode!==null||client.child.signalCode!==null),
   pipesClosed:clients.every(client=>[client.child.stdin,client.child.stdout,client.child.stderr].every(stream=>stream.destroyed)),
   pendingRequests:clients.reduce((n,client)=>n+client.transport.pending.size,0)}
 }finally{writeFileSync(go,'release');await harness.close()}
}
const rows=[]
for(const kind of ['start-abandon','start-timeout','start-failure','close-abandon','close-timeout'])rows.push(await scenario(kind))
process.stdout.write(JSON.stringify(rows))
