import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {boot,recomposeProfile}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/index.ts')).href)
const {createRuntimeResolution}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile.ts')).href)
const {PluginPackages}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile-resolution/service.ts')).href)
function pkg(path:string,name:string,fields:any={}){mkdirSync(path,{recursive:true});writeFileSync(join(path,'package.json'),JSON.stringify({name,version:'1.0.0',...fields}));return join(path,'package.json')}
function fixture(directory:string){
 const home=join(directory,'home'),active=join(home,'profiles/active'),installAnchor=pkg(join(directory,'installation'),'installation')
 pkg(active,'profile',{dependencies:{selected:'*'},dsh:{profile:{bundles:['selected']}}})
 const selected=join(active,'node_modules/selected');pkg(selected,'selected',{dependencies:{private:'*'},dsh:{bundle:{patch:'./patch.yml'}}});writeFileSync(join(selected,'patch.yml'),'[]')
 pkg(join(selected,'node_modules/private'),'private');const path=join(active,'root.json');writeFileSync(path,'[]')
 return {options:{installAnchor,home,profile:{name:'active',dir:active,layers:[{packageName:'selected',packageDir:selected,patches:[],patchPaths:[]}],skippedBundles:[]}},path}
}
const result:any[]=[],raw:any[]=[]
for(const mode of JSON.parse(readFileSync(input,'utf8'))){
 const directory=resolve(dirname(input),'files/source',mode),{options,path}=fixture(directory),resolution=await createRuntimeResolution(options)
 const trace:string[]=[],reload:any[]=[],entered=Promise.withResolvers<void>(),release=Promise.withResolvers<void>();let packages:any
 const row:any={id:'candidate',name:mode==='running-failed'?'cordis:broken':mode==='retry'?'cordis:absent':'cordis:held'}
 let rows:any[]=[{id:'first',name:'cordis:healthy'},row,{id:'last',name:'cordis:healthy'}]
 if(mode==='group')rows=[{id:'group',name:'cordis:group',group:true,config:[row]}]
 const patches=[{insert:rows}];let warning='';const write=process.stderr.write;process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
 let ctx:any
 try{ctx=await boot('probe',path,patches,host=>{
  packages=new PluginPackages(host,{resolution});const original=packages.replace.bind(packages)
  packages.replace=(value:any)=>{trace.push('publish');if(mode==='publish-error')throw new Error('publication failed');original(value)}
  host.loader.builtins.healthy=()=>{}
  host.loader.builtins.broken=()=>{throw new Error('candidate activation failed')}
  host.loader.builtins.held=(owner:any)=>{trace.push('start');owner.effect(()=>async()=>{trace.push(packages.resolution.entries.some((entry:any)=>entry.name==='private')?'stop-old':'stop-new');entered.resolve();if(mode==='held')await release.promise})}
  host.on('app-boot/config-reload',(...args:any[])=>{reload.push(args)})
 })}finally{process.stderr.write=write}
 try{
  const before=[...ctx.loader.entries()].find((row:any)=>row.options.id==='candidate'),fiber=before.fiber,running:any[]=[]
  if(mode==='retry')ctx.loader.builtins.absent=()=>{}
  if(mode.startsWith('running')){running.push(before);ctx.registry.delete(before.fiber.runtime.callback);await before.fiber.await().catch(()=>{});await ctx.loader.await()}
  const removing=['remove','held','group','restart','publish-error','read-error'].includes(mode)
  const next=mode==='group'?[]:removing?[{insert:[rows[0],rows.at(-1)]}]:patches
  if(removing){const anchor=join(options.profile.layers[0]!.packageDir,'package.json'),manifest=JSON.parse(readFileSync(anchor,'utf8'));manifest.dependencies={};writeFileSync(anchor,JSON.stringify(manifest))}
  if(mode==='restart'){const anchor=options.installAnchor,manifest=JSON.parse(readFileSync(anchor,'utf8'));manifest.version='2.0.0';writeFileSync(anchor,JSON.stringify(manifest))}
  if(mode==='read-error')writeFileSync(options.installAnchor,'{')
  trace.length=0;let error:any=null,answer:any=null,done=false,settled_before:any=null
  process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
  try{
   const operation=recomposeProfile(ctx,next,'probe',{running}).finally(()=>{done=true})
   if(mode==='held'){await entered.promise;settled_before=done;release.resolve()}
   try{answer=await operation}catch(failure){error=(failure as Error).message}
  }finally{process.stderr.write=write}
  const after=[...ctx.loader.entries()].find((row:any)=>row.options.id==='candidate')
  result.push({mode,fatal:error!==null,restart:answer?.restartReason??null,warnings:answer===null?null:answer.warnings.length,
   same_entry:before===after,same_fiber:!!after&&fiber===after.fiber,active:!!after&&after.fiber?.state===2,candidate:!!after,
   ids:[...ctx.loader.entries()].map((row:any)=>row.options.id).filter((id:string)=>['first','candidate','last','group'].includes(id)),
   trace:[...trace],reload,settled_before,old_table:packages.resolution===resolution})
  raw.push({mode,error,answer,log:warning,options:after?.options,state:after?.fiber?.state,uid:after?.fiber?.uid})
 }finally{release.resolve();await ctx.fiber.dispose()}
}
writeFileSync(resolve(dirname(input),'source-diagnostics.json'),JSON.stringify(raw))
process.stdout.write(JSON.stringify(result))
