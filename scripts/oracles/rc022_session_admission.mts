import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const {Session}=await import(pathToFileURL(resolve(process.argv[2]!,'packages/core/session/src/index.ts')).href)
const {SurfaceManager}=await import(pathToFileURL(resolve(process.argv[2]!,'packages/core/session/src/surface.ts')).href)
const rows=JSON.parse(readFileSync(process.argv[3]!,'utf8')),results=[]
for(const row of rows){
 const result:any={name:row.name}
 try{
  const args=['session',row.events,row.header,row.cut??0]
  const session=row.mode==='create'?Session.create(...args):Session.fromRestore(...args,'detached')
  Object.assign(result,{seq:session.seq,nodes:[...session.surface.nodes],messages:session.deriveMessages(),firstLiveSeq:session.firstLiveSeq,firstLifecycleSeq:session.firstLifecycleSeq,inheritedEventCount:session.inheritedEventCount,types:session.snapshotEvents().map((event:any)=>event.type)})
 }catch(error:any){result.error=error.message}
 results.push(result)
}
for(const action of ['read','remove','replace','remove-pending','unused']){
 const definition={type:'image/offload',project:(event:any,context:any)=>new Map([[0,{...context.events[0].data,content:[{type:'text',text:'projected'}]}]])}
 const definitions=[definition],session=Session.create('projection',undefined,undefined,undefined,definitions)
 session.append('user/message',{id:'user',role:'user',source:{kind:'user'},content:[{type:'text',text:'original'}]},{surfaceOp:'append'})
 const result:any={name:'projection-'+action}
 if(action!=='unused')session.append('image/offload',{})
 if(!['remove-pending','unused'].includes(action))result.before=session.deriveMessages().map((message:any)=>message.content)
 if(['remove','remove-pending','unused'].includes(action))definitions.length=0
 else if(action==='replace')definitions[0]={...definition}
 try{Object.assign(result,{messages:session.deriveMessages().map((message:any)=>message.content),generation:session.surface.contentGeneration,position:session.surface.replaceGeneration})}catch(error:any){result.error=error.message}
 results.push(result)
}
const definitions=[{type:'image/offload',project:()=>new Map()}],manager=new SurfaceManager([],0,definitions)
manager.validateNext({type:'image/offload',seq:0,time:1,data:{}});definitions.length=0
results.push({name:'projection-uncommitted',nodes:[...manager.nodes]})
process.stdout.write(JSON.stringify(results))
