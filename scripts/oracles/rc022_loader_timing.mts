import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,load=(path:string)=>import(pathToFileURL(resolve(root,path)).href)
const {Context}=await load('vendor/cordis/src/context.ts'),{default:Loader}=await load('vendor/loader/src/index.ts')
const result:any={}
for(const mode of ['remove','stop','replace','import','concurrent-import']){
  const ctx=new Context();await ctx.plugin(Loader);const loader=ctx.loader
  let enter!:()=>void,release!:()=>void
  const entered=new Promise<void>(r=>enter=r),gate=new Promise<void>(r=>release=r),cleaned:boolean[]=[],calls:any[]=[],partials:any[]=[],commits:string[]=[]
  const example=(owner:any,config:any)=>{calls.push(config.value);if(mode==='remove'||mode==='stop')owner.effect(()=>async()=>{enter();await gate;cleaned.push(true)})}
  loader.builtins.example=example;loader.commit=(change:any)=>{commits.push(change.options?change.options.id:'-'+change.id)}
  ctx.on('loader/partial-dispose',(entry:any,_old:any,partial:boolean)=>{partials.push([entry.options.id,partial])})
  const options={id:'a',name:'cordis:example',config:{value:1}}
  try{
    if(mode==='import'||mode==='concurrent-import'){
      let finish!:(value:any)=>void;const imported=new Promise(r=>finish=r)
      loader.import=()=>{calls.push('import');return imported}
      const pending=loader.create(options),second=mode==='concurrent-import'?loader.store.a.init():undefined
      result[mode]={prefix:[...calls],pending:!!loader.getTasks().length,registered:'a'in loader.store}
      finish(example);await pending;await second;await loader.await();result[mode].calls=calls;continue
    }
    await loader.create(options);await loader.await();const entry=loader.store.a,fiber=entry.fiber
    if(mode==='replace'){
      const newer={id:'a',name:'cordis:example',config:{value:2}},pending=loader.root.create(newer)
      result[mode]={published:entry.options===newer,partials:[...partials]};await pending;await loader.await()
      const empty=loader.root.update([]);Object.assign(result[mode],{empty_pending:!!loader.getTasks().length,empty_store:Object.keys(loader.store),calls});await empty
    }else{
      const pending=mode==='remove'?loader.remove('a'):loader.root.stop()
      result[mode]={registered:'a'in loader.store,rows:loader.root.data.length,retained:entry.fiber===fiber,disposed:!fiber.uid,
        partials:[...partials],commits:[...commits],disabled:'disabled'in entry.options}
      await pending;await entered;await loader.await();result[mode].cleanup_pending=!cleaned.length
      let finished=false;const shutdown=ctx.fiber.dispose()!.then(()=>{finished=true})
      result[mode].shutdown_pending=!finished;release();await shutdown;result[mode].cleaned=cleaned
    }
  }finally{release();await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
