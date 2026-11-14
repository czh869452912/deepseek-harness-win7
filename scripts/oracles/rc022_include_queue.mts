/** Unchanged Source Loader and Include, actual files in an owned workspace. */
import {mkdir,readFile,writeFile,rm} from 'node:fs/promises'
import {dirname,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const load=(path:string)=>import(pathToFileURL(resolve(root,path)).href)
const {Context}=await load('vendor/cordis/src/context.ts'),{default:Loader}=await load('vendor/loader/src/index.ts'),{default:Include}=await load('vendor/include/src/index.ts')
const row=(id:string,value:number)=>({id,name:'cordis:example',config:{value}}),result:any={}
for(const mode of ['refresh-first','update-first','conflict','recovery','patch','failed-refresh','duplicate']){
  const directory=resolve(dirname(input),'files/source',mode);await mkdir(directory,{recursive:true})
  const filename=resolve(directory,'root.json'),write=(data:any)=>writeFile(filename,JSON.stringify(data))
  await write(mode==='duplicate'?[row('a',1),row('a',2)]:[row('a',1),row('b',1)])
  const ctx=new Context();ctx.baseUrl=pathToFileURL(directory).href+'/'
  let entered!:()=>void,release!:()=>void
  const started=new Promise<void>(resolve=>entered=resolve),gate=new Promise<void>(resolve=>release=resolve)
  await ctx.plugin(Loader);ctx.loader.builtins.include=Include;ctx.loader.builtins.example=async(_ctx:any,config:any)=>{
    if(mode==='failed-refresh'&&config.value===2){entered();await gate;throw Error('rejected candidate')}
  }
  const id=await ctx.loader.create({name:'cordis:include',config:{path:pathToFileURL(filename).href}})
  await ctx.loader.await();const include=ctx.loader.resolve(id).subtree,errors:any[]=[]
  try{
    if(mode==='duplicate'){result[mode]=[include.root.data.length,Object.keys(include.store),include.store.a.fiber.effectiveConfig];continue}
    if(mode==='refresh-first'||mode==='update-first'){
      await write([row('a',1),row('b',3)])
      if(mode==='refresh-first')await Promise.all([include.refresh(),include.update('a',{config:{value:2}})])
      else await Promise.all([include.update('a',{config:{value:2}}),include.refresh()])
      await include.flush()
    }else if(mode==='conflict'){
      await write([row('a',3),row('b',1)]);await include.update('a',{config:{value:2}});await include.flush()
    }else if(mode==='recovery'){
      await rm(filename);await include.update('a',{config:{value:2}})
      try{await include.flush()}catch(error:any){errors.push([error.name,error.stage??null])}
      await writeFile(filename,'{');try{await include.refresh()}catch(error:any){errors.push([error.name,error.stage??null])}
      if(await readFile(filename,'utf8')!=='{')throw Error('invalid file overwritten')
      await write([row('a',1),row('b',4)]);await include.refresh();await include.flush()
    }else if(mode==='failed-refresh'){
      await write([row('a',2),row('b',1)]);const first=include.refresh();await started
      await write([row('a',3),row('b',1)]);const second=include.refresh();await include._draining
      release();await Promise.all([first,second]);await include.flush()
    }else{
      const inner=resolve(directory,'inner.json'),original=JSON.stringify([row('x',1)]);await writeFile(inner,original)
      const key=await include.create({id:'child',name:'cordis:include',config:{path:pathToFileURL(inner).href,patches:[{id:'x',disabled:true},{insert:[row('y',1)]}]}})
      await ctx.loader.await();const child=include.store.child.subtree
      await child.update('x',{disabled:false});await child.update('y',{config:{value:2}});await child.flush();await include.flush()
      result[mode]=[await readFile(inner,'utf8')===original,JSON.parse(await readFile(filename,'utf8')).at(-1).config.patches];continue
    }
    result[mode]=[['a','b'].map(key=>include.store[key].fiber.effectiveConfig),JSON.parse(await readFile(filename,'utf8')),errors,include.journal.size]
  }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
