import {mkdirSync,readFileSync,writeFileSync,symlinkSync,unlinkSync} from 'node:fs'
import {createRequire} from 'node:module'
import {dirname,join,relative,resolve} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/lib/index.js')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/lib/index.js')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/lib/index.js')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/lib/index.js')).href)
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),result=[]
for(const {name,...options} of input.cases){
 const owner=join(directory,name),base=options.base?join(owner,options.base):owner
 for(const name of input.files){const p=join(base,name);mkdirSync(dirname(p),{recursive:true});writeFileSync(p,'before')}
 if(name==='linked-root'||name==='unfollowed-root')symlinkSync(join(base,'sub'),join(base,'alias'),process.platform==='win32'?'junction':'dir')
 const ctx=new Context();ctx.baseUrl=pathToFileURL(owner).href+'/'
 await ctx.plugin(Loader);await ctx.plugin(Timer)
 try{
  await ctx.plugin(Hmr,{root:['.'],debounce:0,...options});const hmr:any=ctx.hmr,events:string[]=[]
  ctx.on('hmr/change',(url:string)=>{events.push(relative(base,fileURLToPath(url)).replaceAll('\\','/'))})
  for(const name of input.files)writeFileSync(join(base,name),'after-'+name)
  await new Promise(done=>setTimeout(done,350));await hmr.runExclusive(async()=>{})
  result.push({name,ready:true,events:[...new Set(events)].sort()})
  if(name==='empty'){
   const pause=()=>new Promise(done=>setTimeout(done,150)),added=join(base,'added.txt');events.length=0
   writeFileSync(added,'new');await pause();const baseline=[...events]
   writeFileSync(added,'updated');await pause();const changes=[...events];events.length=0
   unlinkSync(added);await pause();const deleted=[...events]
   writeFileSync(added,'restored');await pause();const restored=[...events]
   writeFileSync(added,'restored-edited');await pause();await hmr.runExclusive(async()=>{})
   result.push({name:'membership',added:baseline,changed:changes,deleted,restored,rechanged:[...events]})
  }
 }finally{await ctx.fiber.dispose()}
}
const match=createRequire(resolve(root,'packages/boot/hmr/package.json'))('picomatch')
result.push({name:'ignore-patterns',values:input.patterns.flatMap((pattern:string)=>input.paths.map((path:string)=>match(pattern)(path)))})
process.stdout.write(JSON.stringify(result))
