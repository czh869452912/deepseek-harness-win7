import {load} from './rc022_subagent_fixture.mts'
const {PtcWorkflowRun}=await load('packages/workflow/workflow-ptc/src/host.ts')
async function scenario(kind:string){
 const rows:any[]=[],calls:any[]=[],disposed:string[]=[],warnings:string[]=[];let directory='C:/initial'
 const entered=Promise.withResolvers<void>(),release=Promise.withResolvers<void>(),launched=Promise.withResolvers<void>(),external=new AbortController()
 const ctx={workingDirectory:{async ensure(){calls.push('cwd');if(kind==='directory-failure')throw Error('selected directory unavailable');return directory}},logger:{warn:(value:string)=>warnings.push(value)}}
 const subagents={async startActivation(spec:any){calls.push({provider:spec.provider,label:spec.label,delivery:spec.delivery,cwd:spec.cwd,prompt:spec.prompt,options:spec.agentOptions??null,schema:spec.outputSchema??null});entered.resolve();if(kind==='late-child')await release.promise
  return {childId:'child',result:kind==='cancel-wait'?new Promise(()=>{}):Promise.resolve({output:[{type:'text',text:'child'}],stopReason:'completed',structured:{ok:true}}),async dispose(){disposed.push('child');if(kind==='dispose-failure')throw Error('cleanup refused')}}}}
 const event=(name:string)=>(value:any)=>rows.push({event:name,value}),observer={phase:event('phase'),log:event('log'),agentStart:event('start'),agentEnd:event('end')}
 async function execute(spec:any){
  calls.push({cwd:spec.cwd,timeout:spec.timeoutMs,policy:spec.sandboxPolicy??null,global_:spec.bindings[0].global});const b=spec.bindings[0].functions,initial=await b.begin({});rows.push({begin:structuredClone(initial)});initial.meta.name='detached'
  if(kind==='malformed-result')return {value:{stopReason:'completed',agentsStarted:0}}
  if(kind==='execution-error')return {error:{kind:'timeout',message:'expired'}}
  if(kind==='validation'){
   for(const [name,value] of [['startChild',{}],['startChild',{prompt:'p',model:3}],['childResult',{callId:true}],['childResult',{callId:3}],['progress',{}],['progress',[{type:'phase',title:'must not emit'},{type:'bad'}]],['progress',[{type:'agent-start',info:{seq:0,label:'x',childId:'child'}}]]] as const){try{await b[name](value)}catch(error:any){rows.push({rejected:error.message})}}
  }else{
   if(kind==='fixed-cwd')directory='C:/moved'
   const child=await b.startChild({prompt:'hello',provider:'llm',model:'m',schema:{type:'object',properties:{}}});rows.push({child});const info={seq:1,label:'one',childId:'child'}
   await b.progress([{type:'phase',title:'work'},{type:'agent-start',info}]);launched.resolve()
   try{rows.push({childResult:await b.childResult(child)})}catch{rows.push({childAborted:true})}
   if(kind!=='open-progress'){await b.progress([{type:'agent-end',info:{...info,outcome:'completed'}},{type:'agent-end',info:{...info,outcome:'completed'}}]);await b.disposeChild(child)}
  }
  return {value:{value:7,stopReason:'completed',agentsStarted:1}}
 }
 const runtime={sandboxMode:['unconfined','full-access'].includes(kind)?undefined:'read-only',programFormat:'function-body',resolve:(spec:any)=>spec,run:execute}
 if(kind==='already-aborted')external.abort('external')
 const init={meta:{name:'host',description:'contract'},body:'return 7',limits:{maxConcurrentAgents:2,maxTotalAgents:10,maxItemsPerCall:20,syncTimeoutMs:1000}}
 const run=new PtcWorkflowRun(ctx,subagents,runtime,'run',init.meta,{},init,'stub',{mode:kind==='full-access'?'danger-full-access':'read-only'},observer,external.signal)
 if(kind==='late-child'){await entered.promise;run.cancel('stop');release.resolve()}
 if(kind==='cancel-wait'){await launched.promise;run.cancel('stop')}
 const result=await run.result,one=run.dispose(),two=run.dispose();await one
 if(result.error)result.error=result.error.split('\n')[0].replace(/^Error: /,'')
 rows.push({result,calls,disposed,warningCount:warnings.length,sameDisposal:one===two,pending:run.pending.size,children:run.children.size,originalMeta:init.meta.name})
 return {name:kind,rows}
}
const rows=[];for(const kind of ['normal','fixed-cwd','validation','open-progress','malformed-result','execution-error','directory-failure','unconfined','full-access','already-aborted','late-child','cancel-wait','dispose-failure'])rows.push(await scenario(kind))
process.stdout.write(JSON.stringify(rows))
