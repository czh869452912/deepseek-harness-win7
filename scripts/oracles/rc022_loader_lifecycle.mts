/** Entry contracts observed from the fixed Source's real runtime. */
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,load=(path:string)=>import(pathToFileURL(resolve(root,path)).href)
const {Context}=await load('vendor/cordis/src/context.ts'),{default:Loader}=await load('vendor/loader/src/index.ts')
const result:any={}
for(const mode of ['noop','failed','import','name','disabled','create']){
  const ctx=new Context();await ctx.plugin(Loader);const calls:any[]=[],partials:boolean[]=[],errors:string[]=[]
  ctx.loader.builtins.example=(_ctx:any,config:any)=>{calls.push(config.value);if(mode==='failed')throw Error('activation failed')}
  ctx.loader.builtins.other=()=>calls.push('other')
  ctx.on('loader/partial-dispose',(_entry:any,_legacy:any,partial:boolean)=>partials.push(partial))
  const original={value:1},options={id:'a',name:'cordis:example',config:original,disabled:null}
  const observe=async(value:any,label:string)=>{try{await value}catch{errors.push(label)}}
  if(mode==='import')ctx.loader.import=()=>{throw Error('import failed')}
  try{
    await observe(ctx.loader.create(options),'create');await observe(ctx.loader.await(),'wait')
    const entry=ctx.loader.store.a,fiber=entry.fiber
    if(mode==='import'){result[mode]={errors,fiber:!!fiber};continue}
    if(mode==='failed'){await observe(fiber.await(),'fiber');result[mode]={errors,state:fiber.state,calls};continue}
    if(mode==='noop'){
      const updated={value:1};await entry.update({config:updated,disabled:null})
      result[mode]={same_options:entry.options===options,entry_raw:entry.options.config===updated,
        fiber_raw:fiber.rawConfig===original,disabled:'disabled'in entry.options,calls,partials}
    }else if(mode==='name'){
      await entry.update({name:'cordis:other'});await entry.update({config:{value:2}});await ctx.loader.await()
      result[mode]={name:entry.options.name,same_fiber:entry.fiber===fiber,calls,partials}
    }else if(mode==='disabled'){
      await entry.update({disabled:true});result[mode]={retained:entry.fiber===fiber,disposed:!fiber.uid,partials:[...partials]}
      await entry.update({disabled:false});await ctx.loader.await();Object.assign(result[mode],{new_fiber:entry.fiber!==fiber,calls})
    }else{
      const updated={id:'a',name:'cordis:example',config:{value:1}}
      await ctx.loader.root.create(updated);await ctx.loader.await()
      result[mode]={new_options:entry.options===updated,same_fiber:entry.fiber===fiber,fiber_raw:fiber.rawConfig===original,calls,partials}
    }
  }finally{await ctx.fiber.dispose()}
}
for(const mode of ['init-gate','update-gate']){
  const ctx=new Context();await ctx.plugin(Loader);let enter!:()=>void,release!:()=>void,activated!:()=>void
  const entered=new Promise<void>(r=>enter=r),gate=new Promise<void>(r=>release=r),calls:string[]=[]
  ctx.loader.builtins.example=async(_ctx:any,config:any)=>{if(config.wait){enter();await gate}}
  await ctx.loader.create({id:'a',name:'cordis:example',config:{wait:mode==='init-gate'}})
  if(mode==='update-gate')await ctx.loader.await()
  const fiber=ctx.loader.store.a.fiber,updating=mode==='update-gate'?fiber.update({wait:true}):Promise.resolve()
  await entered
  const activation=new Promise<void>(r=>activated=r)
  const consumer=ctx.registry.inject({loader:{await:true}},()=>{calls.push('active');activated()})
  const before=consumer.state;release();await updating;await ctx.loader.await();await fiber.await()
  if(mode==='init-gate')await activation
  await consumer.await()
  result[mode]={before,after:consumer.state,calls}
  await ctx.fiber.dispose()
}
process.stdout.write(JSON.stringify(result))
