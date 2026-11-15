import {readFileSync,mkdirSync,writeFileSync,readdirSync} from 'node:fs'
import {join,relative} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Fs}=await load('packages/fs/fs-local/src/index.ts'),Policy=await load('packages/fs/fs-observation-policy/src/index.ts'),{FsError}=await load('packages/fs/fs/src/index.ts'),{executePatch}=await load('packages/fs/tool-fs/src/patch/index.ts'),{FsSandboxController}=await load('packages/fs/tool-fs/src/sandbox.ts')
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),root=join(input.workspace,'source'),rows:any[]=[]
for(const item of input.cases){
 const base=join(root,item.name),workspace=join(base,'workspace'),provider=join(base,'provider');mkdirSync(workspace,{recursive:true});mkdirSync(provider)
 const ctx=new Context();await ctx.plugin(Fs,{cwd:provider});ctx.provide('workingDirectory');ctx.workingDirectory={ensure:async()=>workspace};if(item.policy!==false)await ctx.plugin(Policy)
 const abort=new AbortController(),exec:any={signal:abort.signal,agent:{session:{}}},fs=ctx.fs,observations:any[]=[],target=(path:string)=>fs.resolve(join(workspace,path))
 for(const path of item.directories??[])mkdirSync(join(workspace,path),{recursive:true})
 for(const [path,content] of Object.entries(item.files??{})){writeFileSync(join(workspace,path),content as string);if(!(item.unread??[]).includes(path)){const file=await target(path);ctx.emit('fs/observed',file,{kind:'present',version:(await fs.stat(file))!.version},exec)}}
 for(const path of item.absent??[])ctx.emit('fs/observed',await target(path),{kind:'absent'},exec)
 for(const path of item.stale??[])writeFileSync(join(workspace,path),'changed\n')
 ctx.on('fs/observed',(file:any,value:any)=>{observations.push({path:file.displayPath,kind:value.kind});if(['cancel-between','cancel-last'].includes(item.hook))abort.abort()})
 if(['remove-denied','move-remove-denied'].includes(item.hook))fs.internals.removeFile=()=>{throw Object.assign(Error('removal denied'),{code:'EACCES'})}
 if(item.hook==='cancel-staged'){let count=0;fs.internals.inspectTemp=()=>{if(++count===2)abort.abort()}}
 if(['io-unchanged','io-published','unexpected','aborted-mutation','post-write-stat-failure'].includes(item.hook)){const original=fs.patchText.bind(fs);fs.patchText=async(...args:any[])=>{if(['io-published','post-write-stat-failure'].includes(item.hook))await original(...args);if(item.hook==='post-write-stat-failure')fs.stat=async()=>{throw new FsError('stat failed','FS_IO_ERROR')};if(item.hook==='unexpected')throw Error('defect');if(item.hook==='aborted-mutation'){abort.abort();throw new FsError('patch aborted','FS_ABORTED')}throw new FsError('reply lost','FS_IO_ERROR')}}
 try{
  let report;try{report=await executePatch(ctx,new FsSandboxController(ctx),exec,{patch:item.patch})}catch(error:any){report={thrown:{code:error.code??null,message:error.message}}}
  const files:any={};function scan(directory:string){for(const entry of readdirSync(directory,{withFileTypes:true})){const path=join(directory,entry.name);if(entry.isDirectory())scan(path);else files[relative(workspace,path).replaceAll('\\','/')]=readFileSync(path,'utf8')}}scan(workspace)
  rows.push({name:item.name,report,observations,files,providerEmpty:readdirSync(provider).length===0})
 }finally{await ctx.fiber.dispose()}
}
function normalize(value:any):any{if(typeof value==='string')return value.replaceAll(root,'<root>');if(Array.isArray(value))return value.map(normalize);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]));return value}console.log(JSON.stringify(normalize(rows)))
