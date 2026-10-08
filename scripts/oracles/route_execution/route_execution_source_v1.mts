import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {existsSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'

const options=Object.fromEntries(process.argv.slice(2).reduce((pairs:string[][],value,index,args)=>{
  if(value.startsWith('--'))pairs.push([value.slice(2),args[index+1]])
  return pairs
},[]))
if(!options.root||!options['run-dir']||!options.workspace||!options.output)throw new Error('Explicit route execution roots required')
const root=resolve(options.root),run=resolve(options['run-dir']),workspace=resolve(options.workspace),output=resolve(options.output)
if(existsSync(run)||existsSync(output))throw new Error('Fresh route execution artifacts required')
const fixture=join(dirname(fileURLToPath(import.meta.url)),'route_execution_fixture_v1.mts')
const {runProfile}=await import(pathToFileURL(join(root,'apps/cli/src/profile-boot.ts')).href)
const {createLaunchEnvironmentSnapshot}=await import(pathToFileURL(join(root,'packages/util/launch-environment/src/index.ts')).href)
const {createUserMessage}=await import(pathToFileURL(join(root,'packages/llm/llm/src/index.ts')).href)
const yaml=await import(pathToFileURL(join(root,'node_modules/js-yaml/index.js')).href)
const home=join(run,'home'),profile=join(home,'profiles/web')
mkdirSync(profile,{recursive:true});mkdirSync(workspace,{recursive:true})
writeFileSync(join(profile,'package.json'),JSON.stringify({name:'route-execution-fixture',private:true,type:'module',
  dsh:{profile:{bundles:['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'],patchReload:'startup'}}})+'\n','utf8')
writeFileSync(join(profile,'cordis.patch.yml'),yaml.dump([
  {insert:[{id:'route-execution-fixture',name:pathToFileURL(fixture).href}]},
  {id:'agent-default-model',config:{provider:'route-alpha',model:'parent'}},
  {id:'subagent-model-selection-settings',config:{enabled:true,allowedModels:[{provider:'route-alpha',model:'parent'},{provider:'route-beta',model:'child'}]}},
  {id:'session-persistence-jsonl',config:{root:join(run,'sessions'),packChunks:false}},
  {id:'session-title-llm',disabled:true},
]),'utf8')
process.env.DSH_HOME=home;process.env.DSH_TELEMETRY_DISABLED='1';process.chdir(workspace)
Date.now=()=>1791244800000
const record:any={sourceRoot:root,node:process.version,sourceCommit:execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  observedClock:1791244800000,lookups:[],requests:[],events:[],created:[],disposed:[],cancellation:[],rows:[],
  fixtureSha256:createHash('sha256').update(readFileSync(fixture)).digest('hex')}
;(globalThis as any).__routeExecutionProbe=record
let runtime:any
async function bounded(promise:Promise<unknown>){
  let timer:ReturnType<typeof setTimeout>
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Route execution timeout')),30000)})])}
  finally{clearTimeout(timer!)}
}
try{
  runtime=await runProfile({profile:'web',patchFiles:[],args:['--no-open','--port',options.port??'0'],
    environment:createLaunchEnvironmentSnapshot([{source:'process',values:{DSH_HOME:home,DSH_TELEMETRY_DISABLED:'1'}}])})
  const ctx=runtime.ctx
  record.port=ctx.get('webServer').port
  for(const scenario of ['SPAWN_INHERIT','SPAWN_CHANGE','SPAWN_EFFORT','DENIED_ROUTE','HALF_ROUTE','FORK_INHERIT','CANCEL']){
    const offsets=Object.fromEntries(['lookups','requests','events','created','disposed','cancellation'].map(key=>[key,record[key].length]))
    const childStarted=new Promise<void>(release=>record.childStarted=release)
    const identity='route-parent-'+scenario.toLowerCase()
    await ctx.get('sessionController').create({sessionId:identity,cwd:workspace,agentPreset:'standard'})
    const parent=ctx.get('agents').get(identity)
    parent.followup(createUserMessage({content:[{type:'text',text:scenario}],source:{kind:'user'}}))
    if(scenario==='CANCEL'){await bounded(childStarted);parent.cancel({kind:'user'})}
    await bounded(parent.whenIdle())
    await ctx.get('sessions').flush(parent.session)
    record.rows.push({name:scenario,parentHeader:structuredClone(parent.session.header),parentStatus:parent.status,
      public:Object.fromEntries(Object.entries(offsets).map(([key,offset])=>[key,structuredClone(record[key].slice(offset))]))})
  }
}catch(error:any){record.failure={name:error.name,message:error.message,stack:error.stack};process.exitCode=1}
finally{
  delete record.childStarted
  if(runtime)await runtime.shutdown.shutdown(record.failure?1:0)
  record.exitCode=process.exitCode??0
  mkdirSync(dirname(output),{recursive:true})
  writeFileSync(output,JSON.stringify(record,null,2)+'\n',{encoding:'utf8',flag:'wx'})
}
