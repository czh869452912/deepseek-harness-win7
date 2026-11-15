import {mkdir,readFile,writeFile,appendFile,unlink,stat,readdir} from 'node:fs/promises'
import {resolve,dirname,join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {createHash} from 'node:crypto'
const source=process.argv[2]!, workspace=resolve(dirname(process.argv[3]!),'files/source')
const load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const {createJsonlGenerationRuntime}=await load('packages/session/session-persistence-jsonl/src/generation.ts')
const {prepareCatalogFacts}=await load('packages/session/session-persistence-jsonl/src/catalog-migration.ts')
const {createSessionFormatCatalogWithChildren}=await load('packages/session/session-format-catalog/src/index.ts')
const {generationLogFilename}=await load('packages/session/session-persistence-jsonl/src/format.ts')
const {compressZstdFrame}=await load('packages/session/session-persistence-jsonl/src/zstd.ts')
const cases=JSON.parse(await readFile(process.argv[3]!,'utf8')),results=[]
for(const {name,compression} of cases){
 const root=join(workspace,compression+'-'+name),child=join(root,'child');await mkdir(child,{recursive:true})
 const header={version:3,id:'parent',createdAt:1,isSeeded:false,delegationDepth:0}
 const childHeader={...header,id:'child',createdAt:2,delegationDepth:1,parentSession:'parent',origin:'subagent'}
 const encode=async(value:any)=>{const raw=Buffer.from(JSON.stringify({type:'session',...value})+'\n');return compression==='none'?raw:await compressZstdFrame(raw)}
 const from=join(root,generationLogFilename(3,compression)),target=join(root,generationLogFilename(4,compression)),childPath=join(child,generationLogFilename(3,compression))
 const original=await encode(header);await writeFile(from,original);await writeFile(childPath,await encode(childHeader))
 const facts=await prepareCatalogFacts('parent',[{path:childPath,header:childHeader}],compression,new AbortController().signal)
 const calls:string[]=[]
 const mutate=async()=>name==='deleted'?await unlink(childPath):await appendFile(childPath,'changed')
 const validate=async()=>{calls.push('related');await Promise.resolve();await facts.validate()}
 const verify=async(path:string,encoding:string,id:string,count:number,prefix?:any)=>{
  calls.push('verify');const data=await readFile(path);if(name==='during-verify')await mutate()
  const bytes=prefix?.bytes??data.length;return {identity:await stat(path,{bigint:true}),bytes,digest:createHash('sha256').update(data.subarray(0,bytes)).digest('hex')}
 }
 const runtime=createJsonlGenerationRuntime({barrier:async(phase:string)=>{calls.push(phase);if(phase==='before-source-check'&&name==='at-source-check')await mutate()}})
 const controller=new AbortController(),result:any={name,compression}
 const failure=(error:any)=>error.code==='ENOENT'?'missing':error.name
 try{
  if(name==='before-prepare')await mutate()
  const sessionFormatCatalog=createSessionFormatCatalogWithChildren(facts.facts)
  const prepared=await runtime.prepare({sourcePath:from,sourceVersion:3,currentPath:target,compression,
   format:{currentVersion:4,createRestore:(value:any)=>sessionFormatCatalog.createRestore(value,{recovery:'recoverable',validation:'transformed'}),encodeHeader:sessionFormatCatalog.encodeCurrentHeader.bind(sessionFormatCatalog),encodeEvent:sessionFormatCatalog.encodeCurrentEvent.bind(sessionFormatCatalog)},
   validateRelatedSources:validate,verifyCurrentFile:verify,signal:controller.signal})
  result.prepared=prepared.artifact.header.version
  if(['after-prepare','deleted','retry-failure'].includes(name))await mutate()
  if(name==='cancel-after-prepare')controller.abort(new Error('load cancelled'))
  try{
   if(name==='concurrent'){const first=prepared.publish(),second=prepared.publish();result.samePublication=(await first)===(await second)}else await prepared.publish()
   result.published=true
  }catch(error){result.error=failure(error);if(name==='retry-failure'){try{await prepared.publish()}catch(repeated){result.sameFailure=repeated===error}}}
 }catch(error){result.error=failure(error)}
 result.calls=calls;result.target=await stat(target).then(()=>true,()=>false);result.sourceUnchanged=original.equals(await readFile(from));result.stages=(await readdir(root)).filter(name=>name.endsWith('.tmp')).length;result.children=facts.facts[0].descriptorCount
 results.push(result)
}
process.stdout.write(JSON.stringify(results))
