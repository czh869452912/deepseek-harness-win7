import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { mkdirSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { build } from './node_modules/esbuild/lib/main.js'
import { readFileSync,writeFileSync } from 'node:fs'

const sourceCommit='cd5ef8148158c3a752a658978873241fdf8e2bbc'
if(process.version!=='v22.22.2') throw new Error('Source host observations require pinned Node22.22.2')
if(execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim()!==sourceCommit
  ||execFileSync('git',['-C','reference','status','--porcelain'],{encoding:'utf8'}).trim()) throw new Error('Source pin differs')
const output=resolve(process.argv[2])
if(existsSync(output)) throw new Error('Source host observations require a new output')
mkdirSync(output)
const inputs={}
for(const [entry,format,name] of [
  ['reference/packages/workflow/workflow-worker-thread/src/host.ts','esm','host.mjs'],
  ['reference/packages/workflow/workflow-worker-thread/src/worker.ts','cjs','worker.cjs']
]){
  const built=await build({entryPoints:[entry],bundle:true,platform:'node',format,write:false,metafile:true,
    tsconfig:'reference/tsconfig.base.json',
    alias:{'@deepseek-ai/dsh-llm':resolve('scripts/native/workflow/llm.ts'),
      '@deepseek-ai/dsh-session':resolve('scripts/oracles/javascript_workflow_session.ts'),
      '@deepseek-ai/dsh-tools':resolve('reference/packages/core/tools/src/json-schema.ts')}})
  writeFileSync(resolve(output,name),built.outputFiles[0].contents)
  for(const path of Object.keys(built.metafile.inputs)) inputs[path]=createHash('sha256').update(readFileSync(path)).digest('hex')
}
const {WorkerRun}=await import(pathToFileURL(resolve(output,'host.mjs')).href)
const cases=JSON.parse(readFileSync('tests/fixtures/javascript-workflow/cases.json','utf8'))
const observations=[]
for(const scenario of cases){
  const events=[],requests=[],children=[]
  let finishLate
  const late=new Promise(accept=>{finishLate=accept})
  const meta={name:scenario.name,description:'actual Source host RPC'}
  const signal=new AbortController()
  if(scenario.cancelBeforeGo) signal.abort()
  let run
  const parent={id:'parent',options:{}}
  const provider={async start(route,request){
    requests.push({route,prompt:request.prompt,outputSchema:request.outputSchema,agentOptions:request.agentOptions,
      parentSame:request.parent===parent,abortedAtStart:request.signal.aborted})
    if(scenario.cancelAtStart) run.cancel('active child cancellation')
    const prompt=request.prompt[0].text
    const result=prompt==='failed'?{output:[],stopReason:'error'}:prompt==='blocks'?{
      output:[{type:'text',text:'first'},{type:'image',data:'ignored'},{type:'text',text:'second'}],stopReason:'completed'}:{
      output:[{type:'text',text:prompt}],stopReason:'completed',
      ...request.outputSchema&&prompt!=='unhonored'?{structured:{answer:42}}:{}}
    const child={id:'child-'+requests.length,result:Promise.resolve(result),disposed:0,
      async dispose(){child.disposed++}}
    children.push(child)
    return child
  }}
  const init={body:scenario.body,meta,args:{nested:{value:2}},limits:{maxConcurrentAgents:scenario.concurrent??2,
    maxTotalAgents:scenario.total??10,maxItemsPerCall:scenario.items??30,syncTimeoutMs:200}}
  run=new WorkerRun({logger:{warn:message=>events.push({type:'warning',message})}},provider,'run',meta,parent,init,'spawn',200,
    {phase:title=>events.push({type:'phase',title}),log:message=>{events.push({type:'log',message});finishLate()},
      agentStart:info=>events.push({type:'agent-start',info}),agentEnd:info=>{events.push({type:'agent-end',info});
        if(scenario.name==='dropped-child-after-result') finishLate()}},signal.signal)
  events.push({type:'start'})
  run.result.then(result=>events.push({type:'end',outcome:{stopReason:result.stopReason,
    ...result.error!==undefined?{error:result.error}:{},agentsStarted:result.agentsStarted}}))
  let deadline
  const result=await Promise.race([run.result,new Promise((_,reject)=>{deadline=setTimeout(()=>reject(new Error('deadline '+scenario.name)),5000)})])
  clearTimeout(deadline)
  const aliveAfterResult=run.worker.threadId!==-1
  if(scenario.waitDisposals) await Promise.race([late,new Promise((_,reject)=>{
    deadline=setTimeout(()=>reject(new Error('late observation deadline '+scenario.name)),5000)
  })])
  clearTimeout(deadline)
  await run.dispose()
  observations.push({name:scenario.name,result,events,requests,aliveAfterResult,disposed:children.map(child=>child.disposed),
    signalAborted:run.controller.signal.aborted})
  console.log(JSON.stringify({name:scenario.name,events:events.length,children:children.length}))
}
writeFileSync(resolve(output,'source.json'),encodeSource({sourceCommit,inputs,observations})+'\n','utf8')

function encodeSource(value){
  if(typeof value==='number'&&Object.is(value,-0)) return '-0.0'
  if(value===null||typeof value!=='object') return JSON.stringify(value)
  if(Array.isArray(value)) return '['+value.map(encodeSource).join(',')+']'
  return '{'+Object.keys(value).filter(key=>value[key]!==undefined)
    .map(key=>JSON.stringify(key)+':'+encodeSource(value[key])).join(',')+'}'
}
