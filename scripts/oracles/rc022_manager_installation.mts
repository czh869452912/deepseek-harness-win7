import {readFileSync} from 'node:fs'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {boot,readProfilePatches}=await load('packages/boot/app-boot/src/index.ts'),{default:Manager}=await load('packages/boot/plugin-manager/src/index.ts'),{default:Timer}=await load('vendor/timer/src/index.ts'),{default:Hmr}=await load('packages/boot/hmr/src/index.ts'),{remoteMethods}=await load('packages/typert/protocol/src/index.ts')
const data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
async function write(path:string,value:any){await mkdir(join(path,'..'),{recursive:true});await writeFile(path,JSON.stringify(value))}
for(const mode of data.cases){
 const home=join(data.workspace,'source',mode),dir=join(home,'profile');await mkdir(dir,{recursive:true})
 await write(join(home,'package.json'),{name:'installation'});await write(join(dir,'package.json'),{name:'profile',dependencies:{},dsh:{profile:{bundles:['core']}}})
 await write(join(dir,'node_modules/core/package.json'),{name:'core',version:'1.0.0',dsh:{bundle:{patch:'patch.yml'}}});await write(join(dir,'node_modules/core/patch.yml'),[{insert:[{id:'manager',name:'cordis:manager',config:{lockWaitMs:0}}]}])
 await write(join(dir,'cordis.yml'),[]);await write(join(dir,'cordis.patch.yml'),[]);await write(join(dir,'operation.json'),{mode});await writeFile(join(dir,'pnpm-lock.yaml'),'original\r\n')
 if(mode==='approve')await writeFile(join(dir,'pnpm-workspace.yaml'),'allowBuilds:\n  builder: "set this to true or false"\n')
 const script=join(dir,'package.py');await writeFile(script,data.program)
 const profile:any={name:'test',dir,patchPath:join(dir,'cordis.patch.yml'),installAnchor:join(home,'package.json'),cwd:home,home,startedBundles:['core'],overlays:[],packageManager:{command:data.python,args:[script]}}
 const ctx=await boot('test',join(dir,'cordis.yml'),readProfilePatches('test',profile),(ctx:any)=>{ctx.provide('profileContext',profile);ctx.loader.builtins.manager=Manager;ctx.loader.builtins.active=(owner:any)=>{if(mode==='activation-error')throw new Error('cannot start bundle');owner.provide('installedProbe',true)}})
 const logs:any[]=[],states:any[]=[],facts:any[]=[],changed:any[]=[],tooLate:any[]=[];let waitingResolve:any;const waiting=new Promise<void>(resolve=>{waitingResolve=resolve})
 ctx.on('plugin-manager/install-log',(event:any)=>{logs.push(event);if(event.text.includes('waiting'))waitingResolve()});ctx.on('plugin-manager/operation',(event:any)=>{facts.push(event)});ctx.on('plugin-manager/changed',(event:any)=>{changed.push(event)});ctx.on('plugin-manager/install-state',(event:any)=>{states.push(event);if(mode==='too-late'&&event.phase==='applying')tooLate.push(ctx.pluginManager.cancelInstall(mode))})
 try{
  const manager=ctx.pluginManager
  if(['live','repeat-live','too-late','activation-error'].includes(mode)){await ctx.plugin(Timer);ctx.provide('appReady',{onReady:(listener:any)=>{listener();return()=>{}}});await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0});await ctx.hmr.runExclusive(()=>{})}
  const options:any={requestId:mode};if(mode==='disabled')options.enabled=false;if(mode==='exact')options.saveExact=true;if(mode==='approve')options.approvedBuilds=['builder']
  const promise=manager.installBundle(mode==='invalid'?'-invalid':'fresh',options),wait=manager.waitForInstall(mode);let cancellation:any=null
  if(mode==='cancel'){await waiting;cancellation=await manager.cancelInstall(mode)}
  const result=await promise,waitResult=await wait,steps=[result]
  if(mode==='repeat-live')steps.push(await manager.installBundle('fresh',{requestId:'repeat'}))
  const installed=ctx.get('installedProbe')===true
  if(mode==='remove-startup')profile.startedBundles.push('fresh')
  if(['startup','live','remove-startup','disabled'].includes(mode))steps.push(await manager.removeBundle('fresh'))
  for(let i=0;i<20;i++)await Promise.resolve()
  const jobs:string[]=[]
  function normalize(value:any):any{
   if(Array.isArray(value))return value.map(normalize)
   if(value===null||typeof value!=='object')return typeof value==='string'?value.split(dir).join('<profile>'):value
   const answer:any=Object.fromEntries(Object.entries(value).filter(([key])=>key!=='logPath').map(([key,item])=>[key,normalize(item)]))
   if('jobId'in answer){if(!jobs.includes(answer.jobId))jobs.push(answer.jobId);answer.jobId=jobs.indexOf(answer.jobId)}
   if(mode==='activation-error'&&answer.error&&'diagnostic'in answer.error)answer.error.diagnostic=true
   return answer
  }
  const manifest=JSON.parse(await readFile(join(dir,'package.json'),'utf8'))
  rows.push(normalize({name:mode,steps,waitSame:JSON.stringify(waitResult)===JSON.stringify(result),cancel:cancellation,tooLate:await Promise.all(tooLate),afterWait:await manager.waitForInstall(mode),afterCancel:await manager.cancelInstall(mode),installed,removed:ctx.get('installedProbe')===undefined,selection:manifest.dsh.profile.bundles,dependencies:manifest.dependencies??{},lock:await readFile(join(dir,'pnpm-lock.yaml'),'utf8'),pending:mode==='invalid'?(await manager.inspect('fresh')).status:null,logs,states,changed,facts:facts.map(({id,time,...rest})=>rest),remotes:['installBundle','removeBundle','cancelInstall','waitForInstall'].every(name=>remoteMethods(manager).some((row:any)=>row.method===name))}))
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(rows))
