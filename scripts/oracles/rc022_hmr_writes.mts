import {mkdirSync,readFileSync,writeFileSync,unlinkSync} from 'node:fs'
import {resolve,dirname,join,basename} from 'node:path'
import {fileURLToPath,pathToFileURL} from 'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8'))
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/lib/index.js')).href)
const {default:Loader}=await import(pathToFileURL(resolve(root,'vendor/loader/lib/index.js')).href)
const {default:Timer}=await import(pathToFileURL(resolve(root,'vendor/timer/lib/index.js')).href)
const {default:Hmr}=await import(pathToFileURL(resolve(root,'packages/boot/hmr/lib/index.js')).href)
const pause=(ms:number)=>new Promise(done=>setTimeout(done,ms)),rows=[]
async function observed(predicate:()=>boolean,message:string){
 const deadline=Date.now()+1000
 while(!predicate()){if(Date.now()>=deadline)throw new Error(message);await pause(5)}
}
for(const {name,gap,editor,...options} of cases){
 const base=join(directory,name),path=join(base,editor?'file.txt~':'file.txt');mkdirSync(base,{recursive:true});writeFileSync(path,'initial')
 const ctx=new Context();ctx.baseUrl=pathToFileURL(base).href+'/'
 await ctx.plugin(Loader);await ctx.plugin(Timer)
 try{
  await ctx.plugin(Hmr,{root:['.'],ignored:[],debounce:0,...options});const events:string[]=[]
  ctx.on('hmr/change',(url:string)=>events.push(readFileSync(fileURLToPath(url),'utf8')))
  if(gap!==undefined){
   unlinkSync(path)
   const deadline=Date.now()+1000
   while((ctx.hmr as any).watcher.getWatched()['.']?.includes(basename(path))){
    if(Date.now()>=deadline)throw new Error('watcher did not observe fixture unlink')
    await pause(5)
   }
   await pause(gap);writeFileSync(path,'replaced');await pause(500);rows.push({name,events:[...events]})
  }
  else if(editor){writeFileSync(path,'edited');await pause(250);rows.push({name,events:[...events]})}
  else{
   writeFileSync(path,'part-1')
   if(name==='plain')await observed(()=>events.length===1&&events[0]==='part-1','watcher did not observe first plain write')
   await pause(90);writeFileSync(path,'part-2-longer')
   if(name==='plain')await observed(()=>events.length===2&&events[0]==='part-1'&&events[1]==='part-2-longer','watcher did not observe second plain write')
   else await pause(90)
   const early=[...events]
   if(name==='stable-dispose'){await ctx.fiber.dispose();await pause(400);rows.push({name,early,after:[...events]});continue}
   await pause(450);const complete=[...events];events.length=0
   const added=join(base,'added.txt');writeFileSync(added,'add-1')
   if(name==='plain')await observed(()=>(ctx.hmr as any).watcher.getWatched()['.']?.includes(basename(added)),'watcher did not inventory fixture add')
   await pause(90);writeFileSync(added,'add-2-longer')
   if(name==='plain')await observed(()=>events.length===1&&events[0]==='add-2-longer','watcher did not observe added-file change')
   await pause(450);const addedEvents=[...events];events.length=0
   writeFileSync(added,'after-add')
   if(name==='plain')await observed(()=>events.length===1&&events[0]==='after-add','watcher did not observe later plain change')
   await pause(450);rows.push({name,early,complete,added:addedEvents,changed:[...events]})
  }
  await ctx.hmr.runExclusive(async()=>{})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
