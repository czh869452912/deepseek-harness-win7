import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {existsSync,lstatSync,mkdirSync,readFileSync,readdirSync,writeFileSync} from 'node:fs'
import {dirname,join,relative,resolve} from 'node:path'
import {createInterface} from 'node:readline'
import {fileURLToPath,pathToFileURL} from 'node:url'

const options=Object.fromEntries(process.argv.slice(2).reduce((pairs:string[][],value,index,args)=>{
  if(value.startsWith('--'))pairs.push([value.slice(2),args[index+1]])
  return pairs
},[]))
if(!options['source-root']||!options['run-dir']||!options.output||!['minimal','standard','cordis'].includes(options.preset)
    ||!['fresh','cold'].includes(options.phase))throw new Error('Explicit controlled Source browser host options required')
const root=resolve(options['source-root']),run=resolve(options['run-dir']),output=resolve(options.output)
const fixture=join(dirname(fileURLToPath(import.meta.url)),'web_journey_fixture.mts')
const {runProfile}=await import(pathToFileURL(join(root,'apps/cli/src/profile-boot.ts')).href)
const {createLaunchEnvironmentSnapshot}=await import(pathToFileURL(join(root,'packages/util/launch-environment/src/index.ts')).href)
const yaml=await import(pathToFileURL(join(root,'node_modules/js-yaml/index.js')).href)
const sha=(path:string)=>createHash('sha256').update(readFileSync(path)).digest('hex')
const answer=(value:unknown)=>process.stdout.write('DSH_JOURNEY '+JSON.stringify(value)+'\n')

function durableFiles(){
  const directory=join(run,'home/sessions'),result:Record<string,{sha256:string,size:number}>={}
  if(!existsSync(directory))return result
  const pending=[directory]
  while(pending.length){
    const current=pending.pop()!
    for(const entry of readdirSync(current,{withFileTypes:true})){
      const path=join(current,entry.name),stat=lstatSync(path)
      if(stat.isSymbolicLink())throw new Error('Durable journey artifact link refused')
      if(stat.isDirectory())pending.push(path)
      else if(stat.isFile())result[relative(run,path).replaceAll('\\','/')]={sha256:sha(path),size:stat.size}
      else throw new Error('Durable journey artifact path refused')
    }
  }
  return result
}

if(existsSync(output))throw new Error('Fresh browser host receipt required')
mkdirSync(run,{recursive:true})
if(!options.workspace||!options.clock||!options['approval-artifact'])throw new Error('Controlled workspace, clock and approval artifact required')
const workspace=resolve(options.workspace),home=join(run,'home'),profile=join(home,'profiles/web')
mkdirSync(workspace,{recursive:true})
const before=durableFiles()
if(options.phase==='fresh'&&Object.keys(before).length||options.phase==='cold'&&!Object.keys(before).length){
  throw new Error('Browser journey durable phase precondition differs')
}
mkdirSync(profile,{recursive:true})
writeFileSync(join(profile,'package.json'),JSON.stringify({name:'controlled-browser-journey',private:true,type:'module',
  dsh:{profile:{bundles:['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'],patchReload:'startup'}}},null,2)+'\n','utf8')
writeFileSync(join(profile,'cordis.patch.yml'),yaml.dump([
  {insert:[{id:'web-journey-fixture',name:pathToFileURL(fixture).href}]},
  {id:'agent-default-model',config:{provider:'web-journey-fixture',model:'fixture'}},
  {id:'session-persistence-jsonl',config:{root:join(home,'sessions'),packChunks:false}},
]),'utf8')
process.env.DSH_HOME=home
process.env.DSH_TELEMETRY_DISABLED='1'
process.chdir(workspace)
const observedClock=Number(options.clock)
if(!Number.isSafeInteger(observedClock))throw new Error('Integer controlled clock required')
const realNow=Date.now
const clockCallers:Record<string,number>={}
Date.now=()=>{
  const caller=(new Error().stack?.split('\n')[2]??'').replaceAll('\\','/')
  const controlled=caller.includes('/packages/core/session/')||caller.includes('/packages/context/time-context/')
  const category=controlled?'session-or-prompt':'host-wall-clock'
  clockCallers[category]=(clockCallers[category]??0)+1
  return controlled?observedClock:realNow()
}
const record:any={sourceRoot:root,node:process.version,phase:options.phase,preset:options.preset,observedClock,
  sourceCommit:execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  lookups:[],requests:[],events:[],cancellation:[],snapshots:[],approvalArtifact:resolve(options['approval-artifact']),
  durableBefore:before,fixtureSha256:sha(fixture)}
record.clockCallers=clockCallers
;(globalThis as any).__webJourneyProbe=record
let runtime:any,lines:ReturnType<typeof createInterface>|undefined
try{
  if(process.env.DSH_WEB_JOURNEY_PRELOAD_PWSH==='1'){
    const path=join(root,'packages/shell/tool-pwsh-persistent/lib/index.js')
    record.preloadedModule={path,sha256:sha(path)}
    await import(pathToFileURL(path).href)
  }
  runtime=await runProfile({profile:'web',patchFiles:[],args:['--no-open','--port',options.port??'0'],
    environment:createLaunchEnvironmentSnapshot([{source:'process',values:{DSH_HOME:home,DSH_TELEMETRY_DISABLED:'1'}}])})
  const ctx=runtime.ctx
  let sessionId=options.phase==='cold'?JSON.parse(readFileSync(join(run,'selected-session.json'),'utf8')).sessionId:undefined
  if(options.phase==='fresh'){
    record.preparedWorkspace=await ctx.get('workspaceController').create({path:workspace})
    sessionId='session-11111111-1111-4111-8111-111111111111'
    await ctx.get('sessionController').create({sessionId,workspaceId:record.preparedWorkspace.workspace.workspaceId,agentPreset:options.preset})
  }
  record.attachedBeforeBrowser=sessionId!==undefined&&ctx.get('sessions').get(sessionId)!==undefined
  if(options.phase==='cold'&&record.attachedBeforeBrowser)throw new Error('Cold browser fixture eagerly attached its session')
  answer({ready:true,sessionId,phase:options.phase,preset:options.preset,workspace,
    url:ctx.get('connection').authenticatedUrl('http://127.0.0.1:'+ctx.get('webServer').port)})
  lines=createInterface({input:process.stdin,terminal:false})
  let requestedShutdown=false
  for await(const line of lines){
    const request=JSON.parse(line)
    if(request.command==='snapshot'){
      sessionId??=record.events[0]?.sessionId
      const agent=sessionId===undefined?undefined:ctx.get('agents').get(sessionId)
      const session=sessionId===undefined?undefined:ctx.get('sessions').get(sessionId)
      const value={attached:session!==undefined,agentStatus:agent?.status??null,
        header:session?structuredClone(session.header):null,events:session?structuredClone(session.events):[],
        requests:structuredClone(record.requests),cancellation:structuredClone(record.cancellation),
        tools:agent?ctx.get('tools').schemas(agent).map((tool:any)=>tool.name):[]}
      record.snapshots.push(value)
      answer({id:request.id,ok:true,value})
    }else if(request.command==='shutdown'){
      const session=sessionId===undefined?undefined:ctx.get('sessions').get(sessionId)
      if(session)await ctx.get('sessions').flush(session)
      if(sessionId!==undefined)writeFileSync(join(run,'selected-session.json'),JSON.stringify({sessionId})+'\n','utf8')
      answer({id:request.id,ok:true,value:null})
      requestedShutdown=true
      break
    }else throw new Error('Unknown read-only browser fixture command')
  }
  if(!requestedShutdown)throw new Error('Browser fixture controller closed before owned shutdown')
}catch(error:any){
  record.failure={name:error.name,message:error.message,stack:error.stack}
  process.exitCode=1
}finally{
  lines?.close()
  process.stdin.pause()
  if(runtime)await runtime.shutdown.shutdown(record.failure?1:0)
  record.exitCode=process.exitCode??0
  record.durableAfter=durableFiles()
  mkdirSync(dirname(output),{recursive:true})
  writeFileSync(output,JSON.stringify(record,null,2)+'\n',{encoding:'utf8',flag:'wx'})
}
