import {readFile,writeFile,mkdir,stat,readdir} from 'node:fs/promises'
import {resolve,dirname,join} from 'node:path'
import {pathToFileURL} from 'node:url'
import {createHash} from 'node:crypto'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {createJsonlGenerationRuntime}=await load('packages/session/session-persistence-jsonl/src/generation.ts')
const {verifyCurrentGenerationInWorker}=await load('packages/session/session-persistence-jsonl/src/migration-verifier.ts')
const {createSessionFormatCatalogWithChildren}=await load('packages/session/session-format-catalog/src/index.ts')
const {generationLogFilename}=await load('packages/session/session-persistence-jsonl/src/format.ts')
const {compressZstdFrame}=await load('packages/session/session-persistence-jsonl/src/zstd.ts')
const cases=JSON.parse(await readFile(process.argv[3]!,'utf8')),workspace=resolve(dirname(process.argv[3]!),'files/source'),results:any[]=[]
await mkdir(workspace,{recursive:true});const runtime=createJsonlGenerationRuntime({}),hash=(data:Buffer)=>createHash('sha256').update(data).digest('hex')
const line=(value:any)=>JSON.stringify(value)+'\n'
for(const [index,row] of cases.entries()){
 const path=join(workspace,index+'-'+row.name+'.bin'),header=Buffer.from(line(row.header)),events=Buffer.from(row.events.map(line).join('')),tail=Buffer.from(row.tail??'')
 const prefix=row.compression==='none'?Buffer.concat([header,events]):Buffer.concat([await compressZstdFrame(header),await compressZstdFrame(events)])
 let data=row.compression==='none'?Buffer.concat([prefix,tail]):Buffer.concat([await compressZstdFrame(header),await compressZstdFrame(Buffer.concat([events,tail]))]),expected:any
 if(row.physical==='empty')data=Buffer.alloc(0)
 else if(row.physical==='header-no-newline')data=row.compression==='none'?header.subarray(0,-1):await compressZstdFrame(header.subarray(0,-1))
 else if(row.physical==='torn-frame')data=data.subarray(0,-1)
 else if(row.physical==='combined-frame')data=await compressZstdFrame(Buffer.concat([header,events]))
 if(row.prefix){data=Buffer.concat([prefix,tail]);expected={bytes:prefix.length,digest:hash(prefix)};if(row.prefix==='short')expected.bytes=data.length+1;else if(row.prefix==='different')expected.digest='0'.repeat(64)}
 await writeFile(path,data);const result:any={name:row.name,compression:row.compression}
 for(const action of row.worker?['direct','worker']:['direct']){
  try{
   const args=[path,row.compression,row.expectedId??'session',row.expectedEventCount??row.events.length,expected]
   const value=await (action==='direct'?runtime.verify(...args):verifyCurrentGenerationInWorker(...args)),size=expected?.bytes??data.length
   result[action]={bytes:value.bytes===size,digest:value.digest===hash(data.subarray(0,size))}
  }catch(error:any){result[action]=error.message.replaceAll(path,'<file>')}
 }
 results.push(result)
}
for(const compression of ['none','zstd'])for(const version of [0,1,2,3]){
 const root=join(workspace,'publish-'+compression+'-'+version);await mkdir(root)
 const source=join(root,generationLogFilename(version,compression)),target=join(root,generationLogFilename(4,compression))
 const header={type:'session',version,id:'parent',createdAt:1,delegationDepth:0,...version<2?{seedLength:0}:{isSeeded:false}}
 const raw=Buffer.from(line(header)),original=compression==='none'?raw:await compressZstdFrame(raw);await writeFile(source,original)
 const catalog=createSessionFormatCatalogWithChildren([]),result:any={name:'publish-'+version,compression}
 try{
  const prepared=await runtime.prepare({sourcePath:source,sourceVersion:version,currentPath:target,compression,
   format:{currentVersion:4,createRestore:(value:any)=>catalog.createRestore(value,{validation:'transformed',recovery:'recoverable'}),encodeHeader:catalog.encodeCurrentHeader.bind(catalog),encodeEvent:catalog.encodeCurrentEvent.bind(catalog)},verifyCurrentFile:verifyCurrentGenerationInWorker})
  await prepared.publish();result.published=true;const verified=await runtime.verify(target,compression,'parent',prepared.artifact.events.length);result.verified=verified.bytes===(await stat(target)).size
 }catch(error:any){result.error=error.message.replaceAll(root,'<root>')}
 Object.assign(result,{sourceUnchanged:original.equals(await readFile(source)),target:await stat(target).then(()=>true,()=>false),stages:(await readdir(root)).filter(name=>name.endsWith('.tmp')).length});results.push(result)
}
process.stdout.write(JSON.stringify(results))
