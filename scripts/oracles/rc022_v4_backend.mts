import {mkdir,readFile,writeFile,appendFile,unlink,stat,readdir} from 'node:fs/promises'
import {resolve,dirname,join,basename} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts'),Backend=await load('packages/session/session-persistence-jsonl/src/index.ts')
const {Session}=await load('packages/core/session/src/index.ts'),{imageOffloadProjection}=await load('packages/compaction/compaction-image-offload/src/projection.ts')
const {generationLogPath}=await load('packages/session/session-persistence-jsonl/src/format.ts'),{compressZstdFrame}=await load('packages/session/session-persistence-jsonl/src/zstd.ts')
const cases=JSON.parse(await readFile(process.argv[3]!,'utf8')),workspace=resolve(dirname(process.argv[3]!),'files/source'),results:any[]=[]
const line=(value:any)=>JSON.stringify(value)+'\n',exists=(path:string)=>stat(path).then(()=>true,()=>false)
async function paths(root:string):Promise<string[]>{const entries=await readdir(root,{withFileTypes:true});return (await Promise.all(entries.map(entry=>entry.isDirectory()?paths(join(root,entry.name)):[join(root,entry.name)]))).flat()}
for(const {action,compression} of cases){
 const root=join(workspace,compression+'-'+action);await mkdir(root,{recursive:true});const ctx=new Context();await ctx.plugin(Backend,{root,compression});const backend=ctx.sessionPersistence
 const header={version:4,id:'parent',createdAt:1,isSeeded:false,delegationDepth:0},originals=new Map<string,Buffer>(),result:any={action,compression};let child:string|undefined
 const rawWrite=async(identity:string,version:number,events:any[]=[],metadata:any={})=>{
  const value:any={...header,id:identity,version,...metadata};if(version<2){delete value.isSeeded;value.seedLength=0}
  const first=Buffer.from(line({type:'session',...value})),body=Buffer.from(events.map(line).join(''))
  const data=compression==='none'?Buffer.concat([first,body]):Buffer.concat([await compressZstdFrame(first),...body.length?[await compressZstdFrame(body)]:[]])
  const path=generationLogPath(root,metadata.cwd,identity,version,compression);await mkdir(dirname(path),{recursive:true});await writeFile(path,data);originals.set(path,data);return path
 }
 const summarize=(snapshot:any)=>({version:snapshot.header.version,status:snapshot.formatStatus??null,location:snapshot.location?basename(snapshot.location.path):null,corpus:snapshot.revision.split(':').at(-1).length===64})
 try{
  if(action==='create'){
   const handle=await backend.create(header);result.pending=summarize(await backend.stat('parent'))
   await handle.append([{type:'user/message',seq:0,time:1,surfaceOp:'append',data:{id:'image',role:'user',source:{kind:'user'},content:[{type:'image',attachment:{}}]}},{type:'image/offload',seq:1,time:1,data:{targets:[{seq:0,imageIndexes:[0]}]}}]);await handle.flush();await handle.close()
  }else{
   const version=/^v[0-3]$/.test(action)?Number(action[1]):3;await rawWrite('parent',version)
   if(!/^v[0-3]$/.test(action)){
    const events:any[]=[{type:'subagent/descriptor',seq:0,time:2,data:{version:3,provider:'spawn',mode:'continuable',label:'worker'}}]
    if(action==='child-invalid')events.push({type:'image/offload',seq:1,time:2,data:{targets:[{seq:0,imageIndexes:[0]}]}})
    child=await rawWrite('child',action==='child-v3'?3:4,events,{parentSession:'parent',origin:'subagent',delegationDepth:1})
   }
   const before=await backend.stat('parent');result.before=summarize(before)
   const reader=await backend.open('parent','read'),initial=await reader.read();await reader.close()
   Object.assign(result,{preparedTypes:initial.events.map((event:any)=>event.type),preparedCatalog:initial.events.filter((event:any)=>event.type==='subagent/catalog').map((event:any)=>event.data),readPublished:await exists(generationLogPath(root,undefined,'parent',4,compression))})
   if(action==='membership-add')await rawWrite('other',4,[],{parentSession:'parent',origin:'subagent',delegationDepth:1})
   else if(action==='membership-remove')await unlink(child!)
   else if(action==='child-changed')await appendFile(child!,'changed')
   else if(action==='unrelated-changed')await rawWrite('unrelated',4)
   result.revisionChanged=(await backend.stat('parent')).revision!==before.revision
   try{const handle=await backend.open('parent','write');await handle.close();result.published=true}catch(error:any){result.publicationError=error.name}
  }
  result.after=summarize(await backend.stat('parent'));result.listed=(await backend.list()).map((item:any)=>item.header.id).sort()
  if(!result.publicationError){const reader=await backend.open('parent','read'),restored=await reader.read();await reader.close();const current=Session.fromRestore('parent',restored.events,header,0,restored.eventState,[imageOffloadProjection]);result.marked=current.deriveMessages().flatMap((message:any)=>message.content.filter((block:any)=>block.type==='image').map((block:any)=>block.offloaded===true));result.eventState=restored.eventState}
 }catch(error:any){result.error=error.message.replaceAll(root,'<root>')}
 finally{await ctx.fiber.dispose()}
 result.sourceUnchanged=true;for(const [path,data] of originals)if(await exists(path)&&!(action==='child-changed'&&path===child)&&!data.equals(await readFile(path)))result.sourceUnchanged=false
 const entries=await paths(root);result.stages=entries.filter(path=>path.endsWith('.tmp')).length;result.locks=entries.filter(path=>path.endsWith('.lock')).length;results.push(result)
}
process.stdout.write(JSON.stringify(results))
