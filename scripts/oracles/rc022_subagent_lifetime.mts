import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href),{default:Manager}=await load('packages/subagent/subagent/src/manager.ts'),{ChildLock}=await load('packages/subagent/subagent/src/activation.ts'),rows:any[]=[]
const agent=(id:string,origin?:string,own=false)=>({id,session:{header:{id,...origin?{origin}:{}},isOwnSeq:()=>own}})
function fixture(){
 const trace:any[]=[],root=agent('root'),parent=agent('parent','subagent',true),child:any=agent('child','subagent',true),live=new Map([root,parent,child].map(agent=>[agent.id,agent]))
 const ctx={agents:{get:(id:string)=>live.get(id)},get:(name:string)=>name==='agents'?ctx.agents:undefined,logger:{warn:()=>trace.push('warning')}}
 const tree=Object.assign(Object.create(Manager.prototype),{ctx,host:{identityOf:()=>undefined,emitLifecycle:()=>trace.push('end')},resident:new Map(),closingRoots:new Set(),draining:false,materializations:new Set(),locks:new ChildLock(),rootPools:new WeakMap()})
 const a:any={kind:'local',childId:'child',runId:'run',provider:'test',root,ancestors:['root','parent'],path:'worker/nested',result:Promise.withResolvers(),closing:undefined,accepted:false,delivery:'caller',failureAt:undefined,structured:undefined,outputStart:0,poke:Promise.withResolvers(),omitClosingText:false}
 void a.result.promise.catch(()=>undefined)
 child.status='idle';child.inbox={nextTurn:[],nextStep:[]};child.session.snapshotEvents=()=>[];child.ctx={sessions:{flush:async()=>{trace.push('flush')}}}
 child.cancel=(cause:any,options?:any)=>trace.push({cancel:cause,options:options??null});child.whenIdle=async()=>{trace.push('idle')}
 a.handle={agent:child,dispose:async()=>{trace.push('handle')}};a.releaseSlot=()=>trace.push('slot');tree.resident.set('child',a);tree.resident.set('parent',{kind:'local',handle:{agent:parent},root,ancestors:['root'],path:'worker',closing:undefined})
 return {tree,a,root,parent,child,live,trace}
}
for(const action of ['user','root','parent','outsider','stale','self','absent','closing','external']){
 const {tree,a,root,parent,child,live,trace}=fixture();let authority:any={kind:'ancestor',agent:root}
 if(action==='user')authority={kind:'user'};else if(action==='parent')authority.agent=parent;else if(action==='outsider'){authority.agent=agent('outsider');live.set('outsider',authority.agent)}
 else if(action==='stale')live.set('root',agent('root'));else if(action==='self')authority.agent=child;else if(action==='absent')tree.resident.delete('child');else if(action==='closing')a.closing=Promise.withResolvers().promise
 else if(action==='external'){a.kind='external';a.controller=new AbortController();a.controller.signal.addEventListener('abort',()=>trace.push({abort:a.controller.signal.reason}));tree.dispose=()=>{trace.push('dispose');return Promise.resolve()}}
 const row:any={kind:'interrupt',action};try{tree.interrupt('child',authority)}catch(error:any){row.error={code:error.code??null,message:error.message}}row.trace=trace;rows.push(row)
}
for(const action of ['local-stop','local-settle','handle-failure','external-stop','external-result-failure']){
 const {tree,a,trace}=fixture();tree.resident.delete('parent');const descendant={};tree.resident.set('descendant',descendant);const failure=Error('provider failure')
 if(action==='handle-failure')a.handle.dispose=async()=>{trace.push('handle');throw failure}
 if(action.startsWith('external')){a.kind='external';a.controller=new AbortController();a.controller.signal.addEventListener('abort',()=>trace.push({abort:a.controller.signal.reason}));const result=Promise.withResolvers();void result.promise.catch(()=>undefined);a.run={result:result.promise,dispose:async()=>{trace.push('handle');result.resolve({output:[],stopReason:'completed'})}};if(action==='external-result-failure')result.reject(failure)}
 const operation=['local-settle','external-result-failure'].includes(action)?tree.close(a,()=>tree.finishDisposal(a,false)):tree.dispose(a),row:any={kind:'dispose',action,same:operation===tree.dispose(a),cutoff:a.closing===operation}
 try{await operation}catch(error:any){row.error=error.code??null}try{row.result=await a.result.promise}catch(error){row.resultErrorSame=error===failure}
 Object.assign(row,{trace,resident:[...tree.resident.keys()],descendantSame:tree.resident.get('descendant')===descendant});rows.push(row)
}
{const {tree,root,child}=fixture();tree.resident.delete('parent');child.inbox.nextTurn=[{}];rows.push({kind:'parked',joined:await tree.waitForTreeWork(root),resident:tree.resident.has('child')})}
{const {tree,a,child}=fixture(),observation=a.poke,states=[tree.settlementState(a,observation)];child.inbox.nextTurn=[{}];states.push(tree.settlementState(a,observation));a.failureAt=0;states.push(tree.settlementState(a,observation));tree.wake(a);states.push(tree.settlementState(a,observation));a.closing=Promise.withResolvers().promise;states.push(tree.settlementState(a,a.poke));rows.push({kind:'readiness',states})}
process.stdout.write(JSON.stringify(rows))
