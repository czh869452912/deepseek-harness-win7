import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const listing=await load('packages/subagent/subagent/src/list-children.ts'),{SubagentError}=await load('packages/subagent/subagent/src/error.ts'),rows:any[]=[]
for(const action of ['walk','direct','path','external-path','invalid-path','historical-id','root-error','branch-corrupt','branch-unavailable','root-projection','branch-projection','missing-query','missing-store','abort-before','abort-root','abort-branch','subagent-error']){
 const entry=(id:string,mode='continuable',name?:string)=>({id,createdAt:1,mode,...mode==='continuable'?{label:id}:{},...name===undefined?{}:{name}})
 const graph:any={root:[entry('a','continuable','alpha'),entry('ext','external','external'),entry('old','unknown'),entry('a','continuable','duplicate')],a:[entry('nested','continuable','nested'),entry('root','continuable','cycle')],nested:[],old:[entry('legacy-nested','continuable','leaf')],'legacy-nested':[]}
 const controller=new AbortController(),trace:string[]=[];let active=0,peak=0
 const primary:any=action==='subagent-error'?new SubagentError('domain failure','DOMAIN_FAILURE'):Object.assign(new Error('read failed'),{code:action==='branch-corrupt'?'SESSION_QUERY_CORRUPT_SESSION':'IO_FAILED'})
 const observeSession=async(id:string,_options:any)=>{if(active!==0)throw Error('observation leaked into the next read');trace.push('read:'+id);await Promise.resolve()
  if(action==='root-error'&&id==='root'||['branch-corrupt','branch-unavailable','subagent-error'].includes(action)&&id==='a')throw primary
  active++;peak=Math.max(peak,active);if(action==='abort-root'&&id==='root'||action==='abort-branch'&&id==='a')controller.abort()
  const projections=action==='root-projection'&&id==='root'||action==='branch-projection'&&id==='a'?{values:{}}:{values:{subagentCatalog:graph[id]}}
  return {projections,[Symbol.dispose](){active--;trace.push('dispose:'+id)}}
 }
 const services:any={sessionQuery:{observeSession},sessions:{get:(id:string)=>id==='a'?{}:undefined}}
 if(action==='missing-query')delete services.sessionQuery;if(action==='missing-store')delete services.sessions;if(action==='abort-before')controller.abort()
 const ctx={get:(name:string)=>services[name]},row:any={action}
 try{let value:any
  if(action==='direct'){value=await listing.listChildren(ctx,'root',controller.signal);row.same=value===graph.root}
  else if(['path','external-path','invalid-path','historical-id'].includes(action)){value=(await listing.resolveAgentPath(ctx,'root',({'path':'alpha/nested','external-path':'external/child','invalid-path':'lead/alpha','historical-id':'legacy-id'} as any)[action],controller.signal))??null}
  else value=await listing.listDescendants(ctx,'root',controller.signal)
  row.value=value
 }catch(error:any){row.error={code:error.code??null,same:error===primary}}
 Object.assign(row,{trace,active,peak});rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
