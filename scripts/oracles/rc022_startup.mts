import {mkdir,writeFile} from 'node:fs/promises'
import {dirname,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!,load=(path:string)=>import(pathToFileURL(resolve(root,path)).href)
const {boot,StartupError}=await load('packages/boot/app-boot/src/index.ts'),{captureStartupComposition}=await load('packages/boot/app-boot/src/startup-diagnostics.ts'),result:any={}
for(const mode of ['optional','required','pending','isolated','missing','root','disabled','bounded']){
 const directory=resolve(dirname(input),'files/source',mode);await mkdir(directory,{recursive:true})
 const path=resolve(directory,'root.json'),row:any={id:['required','pending','isolated','bounded'].includes(mode)?'agent-loop':'optional',name:'cordis:broken',config:{privateValue:'do-not-export'}}
 if(['pending','isolated','bounded'].includes(mode))row.name='cordis:waiting'
 if(mode==='missing')row.name='cordis:not-installed'
 if(mode==='disabled')Object.assign(row,{id:'agent-loop',disabled:true})
 const rows:any[]=[row,{id:'healthy',name:'cordis:healthy'}]
 if(mode==='bounded')rows.push(...Array.from({length:257},(_,i)=>({id:'disabled-'+i,name:'cordis:healthy',disabled:true})))
 await writeFile(path,mode==='root'?'{':JSON.stringify(rows))
 let owner:any,ctx:any,failure:any,warning=''
 const write=process.stderr.write
 process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
 try{ctx=await boot('probe',path,undefined,(host:any)=>{
  owner=host
  host.loader.builtins.broken=()=>{const error=new Error('boom');error.stack='boom';throw error}
  host.loader.builtins.healthy=(owner:any)=>{if(mode==='required')owner.effect(()=>()=>{owner.logger.warn('cleanup warning')})}
  host.loader.builtins.waiting={inject:mode==='bounded'?Array.from({length:257},(_,i)=>'absent'+i):['absent'],apply(){}}
  if(mode==='isolated')host.isolate('absent').provide('absent',{})
 })}catch(error){if(!(error instanceof StartupError))throw error;failure=error;ctx=owner}finally{process.stderr.write=write}
 try{
  const composition=failure?.composition??captureStartupComposition(ctx)
  for(const plugin of composition.plugins)plugin.source=plugin.source.replace(pathToFileURL(directory).href,'$ROOT')
  result[mode]={fatal:!!failure,composition,entries:failure?.entries.map((r:any)=>({id:r.id,module:r.module,required:r.required,fiberState:r.fiberState??null,kind:r.outcome.kind,phase:r.outcome.phase??null}))??[],disposed:ctx.get('loader')===undefined,private:JSON.stringify(composition).includes('do-not-export'),original_cause:!!failure&&failure.cause?.message==='Plugin activation failures',startup_path:!!failure&&failure.startup.configurationPath===path}
  if(mode==='required')result[mode].cleanup_log=failure.startup.messages.some((message:any)=>message.args[0]==='cleanup warning')
  if(mode==='optional')result[mode].warning=warning
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
