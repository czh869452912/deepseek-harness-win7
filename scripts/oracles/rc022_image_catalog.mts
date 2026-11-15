import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Session}=await load('packages/core/session/src/index.ts')
const {foldSurface,deriveEventMessage}=await load('packages/core/session/src/surface.ts')
const {imageOffloadProjection}=await load('packages/compaction/compaction-image-offload/src/projection.ts')
const {sessionFormatCatalog,createSessionFormatCatalogWithChildren}=await load('packages/session/session-format-catalog/src/index.ts')
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),images:any[]=[],catalog:any[]=[]
const session=(name='images',...args:any[])=>Session.create(name,args[0],args[1],args[2],[imageOffloadProjection])
const content=()=>[{type:'text',text:'before'},{type:'image',attachment:{}},{type:'image',attachment:{}},{type:'text',text:'after'}]
const input=(current:any)=>current.append('user/message',{id:'image',role:'user',source:{kind:'user'},content:content()},{surfaceOp:'append'})
const marked=(current:any)=>current.deriveMessages().flatMap((message:any)=>message.content.filter((block:any)=>block.type==='image').map((block:any)=>block.offloaded===true))
const decision=(imageIndexes:number[],seq=0)=>({targets:[{seq,imageIndexes}]})
for(const [index,data] of cases.images.entries()){
 const current=session();input(current);const result:any={name:'invalid-'+index}
 for(const action of ['append','resume','fold']){try{
  if(action==='append')current.append('image/offload',data)
  else{const events=[...current.snapshotEvents(),{type:'image/offload',seq:1,time:1,data}];if(action==='resume')session('seed',events);else foldSurface(events,[imageOffloadProjection])}
  result[action]='accepted'
 }catch(error:any){result[action]=error.message}}
 Object.assign(result,{seq:current.seq,marked:marked(current),generation:current.surface.contentGeneration})
 current.append('image/offload',decision([1]));result.after=marked(current);images.push(result)
}
let current=session();const source=input(current),before=current.deriveMessages()
current.append('image/offload',decision([1]));const after=current.deriveMessages()
const identity:any={name:'identity',marked:marked(current),sameId:after[0].id===before[0].id,untouched:after[0].content[0]===before[0].content[0],
 original:!JSON.stringify(source).includes('offloaded'),old:!JSON.stringify(before).includes('offloaded'),projected:current.deriveEventMessage(source)===after[0],
 nodes:[...current.surface.nodes],position:current.surface.replaceGeneration,generation:current.surface.contentGeneration,decisionMessage:current.deriveEventMessage(current.snapshotEvents().at(-1))}
current.append('image/offload',decision([0]));Object.assign(identity,{final:marked(current),fresh:current.deriveMessages()[0]!==after[0]});images.push(identity)
const events=current.snapshotEvents(),fold=foldSurface(events,[imageOffloadProjection])
const restored=Session.fromRestore(current.id,events,current.header,0,'shared-frozen',[imageOffloadProjection])
const child=session('child',events,{...current.header,id:'child',parentSession:current.id,isSeeded:true},events.length);input(child)
images.push({name:'replay',fold:deriveEventMessage(source,fold.projectedMessages).content,restored:marked(restored),resumed:marked(session('resume',events)),child:marked(child),parent:marked(current)})
for(const action of ['repeat','shadowed','assistant','tool','atomic']){
 current=session();const original=input(current),result:any={name:action}
 try{
  if(action==='repeat'){current.append('image/offload',decision([0]));current.append('image/offload',decision([0]))}
  else if(action==='shadowed'){current.append('user/message',{...original.data,content:[]},{surfaceOp:{op:'replace',startSeq:0,endSeq:0},sourceEventSeqs:[0]});current.append('image/offload',decision([0]))}
  else if(action==='assistant'||action==='tool'){
   const message:any={id:action,role:action,source:action==='assistant'?{kind:'model',provider:'mock',model:'mock'}:{kind:'tool',callId:'call'},content:content()}
   if(action==='tool')message.toolCallId='call'
   const data:any={turn:1,step:1,message};if(action==='assistant')data.stream=[]
   const event=current.append(action==='assistant'?'assistant/message':'tool/result',data,{surfaceOp:'append'});current.append('image/offload',decision([1],event.seq))
  }else current.append([['image/offload',decision([0])],['image/offload',decision([0])]])
 }catch(error:any){result.error=error.message}
 Object.assign(result,{seq:current.seq,marked:marked(current),generation:current.surface.contentGeneration});images.push(result)
}
for(const row of cases.catalog){
 const active=row.children?createSessionFormatCatalogWithChildren([]):sessionFormatCatalog
 const result:any={name:row.name,classification:active.readHeader(row.header)}
 try{
  const restore=active.createRestore(row.header,{validation:row.validation,recovery:row.recovery})
  for(const event of row.events)restore.decodeRow(active.encodeCurrentEvent(event))
  result.artifact=restore.finish()
 }catch(error:any){result.error=error.message}
 catalog.push(result)
}
process.stdout.write(JSON.stringify({images,catalog}))
