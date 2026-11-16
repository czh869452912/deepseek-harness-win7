import fs from 'node:fs'
import {getEventListeners} from 'node:events'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:Authorization,AuthorizationDeclinedError}=await load('packages/credentials/authorization/src/index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],key='provider/login'
for(const mode of input){
 const ctx=new Context(),controller=new AbortController(),records:any={},calls:any[]=[],settled:any[]=[],notices:any[]=[],prompts:any[]=[],sessions:any[]=[]
 const gate=Promise.withResolvers<void>(),entered=Promise.withResolvers<void>()
 if(mode==='stale-record')records[key]={kind:'grant',payload:'old'}
 async function modify(name:string,mutate:any){
  const next=await mutate(records[name])
  if(['commit-cancel','external-commit-cancel','unload-commit'].includes(mode)){entered.resolve();await gate.promise}
  if(mode==='commit-storage-failure')throw new Error('storage unavailable')
  records[name]=next;ctx.emit('credentials/record-updated',name);calls.push('write');return next
 }
 ctx.provide('credentials',{modifyRecord:modify,async describeRecord(name:string){return{configured:name in records}}})
 await ctx.plugin(Authorization);const auth=ctx.authorization
 ctx.on('authorization/settled',(key:string,status:string)=>settled.push({key,status,inFlight:auth.describe(key)?.inFlight??null}))
 if(mode==='settled-listener-failure'){
  ctx.on('authorization/settled',()=>{throw new Error('listener failure')});ctx.on('authorization/settled',async()=>{throw new Error('async listener failure')})
  ctx.on('authorization/settled',()=>{calls.push('later-listener')})
 }
 const interaction={notify(value:any){notices.push(value);if(mode==='notice-failure')throw new Error('notice failed')},async prompt(value:any){
  prompts.push(value);if(['decline','wrapped-decline'].includes(mode))throw new AuthorizationDeclinedError()
  if(mode==='prompt-failure')throw new Error('prompt failed');return'typed'
 }}
 async function run(session:any){
  sessions.push(session);calls.push('run')
  if(['withdrawn-orphan','unload-running','late-commit'].includes(mode)){
   entered.resolve();await gate.promise;if(mode==='late-commit')await session.commit({kind:'grant',payload:'late'});else throw new Error('late failure');return
  }
  if(['missing-write','stale-record'].includes(mode))return
  if(mode==='flow-failure')throw new Error('flow failed')
  if(['decline','wrapped-decline','prompt-failure'].includes(mode)){
   try{await session.prompt({message:'Question'})}catch(error){if(mode==='wrapped-decline')throw new Error('wrapped decline');throw error}
  }
  session.notify({message:'Notice'})
  if(mode==='direct-write')await modify(key,async()=>({kind:'grant',payload:'value'}));else await session.commit({kind:'grant',payload:'value'})
  if(mode==='deleted-record'){delete records[key];ctx.emit('credentials/record-updated',key)}
 }
 const dispose=auth.registerFlow({key,label:'Provider',methods:[{id:'browser',label:'Browser'}],run}),entry=auth.list();let duplicate:any=null,busy:any=null,result:any
 if(mode==='duplicate'){try{auth.registerFlow({key,label:'Other',methods:[],run})}catch(error:any){duplicate=error.code??null}}
 if(mode.startsWith('pre-abort'))controller.abort(new Error('caller withdrew'))
 const request:any={key:['no-flow','pre-abort-no-flow'].includes(mode)?'other/login':key,signal:controller.signal,interaction}
 if(['bad-method','pre-abort-bad-method','empty-method'].includes(mode))request.method=mode==='empty-method'?'':'other'
 if(mode==='settled-reentry')ctx.on('authorization/settled',()=>{if(!calls.includes('reentered')){calls.push('reentered');controller.abort()}})
 const active=auth.begin(request)
 try{
  if(['withdrawn-orphan','unload-running','late-commit','commit-cancel','external-commit-cancel','unload-commit'].includes(mode)){
   await entered.promise;try{await auth.begin({...request})}catch(error:any){busy=error.code??null}
   if(mode.startsWith('unload'))dispose();else if(mode==='external-commit-cancel')controller.abort();else auth.cancel(key)
   if(mode.includes('commit')&&mode!=='late-commit'){calls.push('admitted-aborted:'+String(sessions[0].signal.aborted));gate.resolve()}
   else{const outcome=await active;gate.resolve();await Promise.resolve();await Promise.resolve();await Promise.resolve();result={value:outcome}}
  }
  if(!['withdrawn-orphan','unload-running','late-commit'].includes(mode))result={value:await active}
 }catch(error:any){result={error:{message:error.message,code:error.code??null}}}
 await Promise.resolve();await Promise.resolve();dispose()
 rows.push({mode,entry,result,duplicate,busy,calls,notices,prompts,settled,records,listeners:getEventListeners(controller.signal,'abort').length,after:auth.list()})
 await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(rows))
