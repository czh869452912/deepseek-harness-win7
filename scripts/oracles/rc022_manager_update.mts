import {readFileSync,existsSync} from 'node:fs'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {boot,readProfilePatches}=await load('packages/boot/app-boot/src/index.ts'),{default:Manager}=await load('packages/boot/plugin-manager/src/index.ts'),{default:Timer}=await load('vendor/timer/src/index.ts'),{default:Hmr}=await load('packages/boot/hmr/src/index.ts'),{remoteMethods}=await load('packages/typert/protocol/src/index.ts')
const data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
async function write(path:string,value:any){await mkdir(join(path,'..'),{recursive:true});await writeFile(path,JSON.stringify(value))}
for(const mode of data.cases){
 const home=join(data.workspace,'source',mode),dir=join(home,'profile'),source=mode.startsWith('git-')?'git+https://example.invalid/repository.git#'+'a'.repeat(40):'1.0.0'
 await write(join(home,'package.json'),{name:'installation'});await write(join(dir,'package.json'),{name:'profile',dependencies:{fresh:source},dsh:{profile:{bundles:['core',...mode==='disabled'?[]:['fresh']]}}})
 for(const name of ['core','fresh'])await write(join(dir,'node_modules',name,'package.json'),{name,version:'1.0.0',dsh:{bundle:{patch:'patch.yml'}}})
 await write(join(dir,'node_modules/core/patch.yml'),[{insert:[{id:'manager',name:'cordis:manager',config:{lockWaitMs:0}}]}]);await write(join(dir,'node_modules/fresh/patch.yml'),[{insert:[{id:'fresh-row',name:'cordis:active',config:{version:'1.0.0'}}]}])
 await write(join(dir,'cordis.yml'),[]);await write(join(dir,'cordis.patch.yml'),[]);await write(join(dir,'operation.json'),{mode});await writeFile(join(dir,'pnpm-lock.yaml'),'original\r\n')
 const script=join(dir,'package.py');await writeFile(script,data.program)
 const profile:any={name:'test',dir,patchPath:join(dir,'cordis.patch.yml'),installAnchor:join(home,'package.json'),cwd:home,home,startedBundles:['core'],overlays:[],packageManager:{command:data.python,args:[script]}}
 const ctx=await boot('test',join(dir,'cordis.yml'),readProfilePatches('test',profile),(ctx:any)=>{ctx.provide('profileContext',profile);ctx.loader.builtins.manager=Manager;ctx.loader.builtins.active=(owner:any,config:any)=>{if(mode==='activation-error'&&config.version==='2.0.0')throw new Error('cannot start bundle');owner.provide('installedProbe',config.version)}})
 const logs:any[]=[],states:any[]=[],updates:any[]=[],facts:any[]=[],changed:any[]=[];let waitingResolve:any;const waiting=new Promise<void>(resolve=>{waitingResolve=resolve})
 ctx.on('plugin-manager/install-log',(event:any)=>{logs.push(event);if(event.text.includes('waiting'))waitingResolve()});ctx.on('plugin-manager/install-state',(event:any)=>{states.push(event)});ctx.on('plugin-manager/update-state',(event:any)=>{updates.push(event)});ctx.on('plugin-manager/operation',(event:any)=>{facts.push(event)});ctx.on('plugin-manager/changed',(event:any)=>{changed.push(event)})
 try{
  const manager=ctx.pluginManager
  if(mode!=='startup'){await ctx.plugin(Timer);ctx.provide('appReady',{onReady:(listener:any)=>{listener();return()=>{}}});await ctx.plugin(Hmr,{root:[],ignored:[],debounce:0});await ctx.hmr.runExclusive(()=>{})}
  const options:any={requestId:mode};if(mode==='registry-spec')options.spec='fresh@2.0.0';if(mode==='git-branch')options.spec='git+https://example.invalid/repository.git#main';if(mode==='git-other')options.spec='git+https://example.invalid/other.git#'+'b'.repeat(40)
  const version=mode==='invalid-version'?'bad':mode==='same-version'?'1.0.0':'2.0.0'
  const promise=manager.updateBundle(mode==='unknown'?'missing':'fresh',version,options);let cancellation:any=null
  if(mode==='cancel'){await waiting;cancellation=await manager.cancelInstall(mode)}
  const result=await promise
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
  rows.push(normalize({name:mode,result,cancel:cancellation,probe:ctx.get('installedProbe')??null,selection:manifest.dsh.profile.bundles,dependencies:manifest.dependencies??{},lock:await readFile(join(dir,'pnpm-lock.yaml'),'utf8'),logs,states,updates,changed,facts:facts.map(({id,time,...rest})=>rest),commands:existsSync(join(dir,'runs.jsonl'))?(await readFile(join(dir,'runs.jsonl'),'utf8')).trim().split('\n').map(line=>JSON.parse(line)):[],remote:remoteMethods(manager).some((row:any)=>row.method==='updateBundle')}))
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(rows))
