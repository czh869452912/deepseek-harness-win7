/** Fixed Source Loader/Include, with actual independent persisted trees. */
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {dirname,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const load=(path:string)=>import(pathToFileURL(resolve(root,path)).href)
const {Context}=await load('vendor/cordis/src/context.ts'),{default:Loader,Group}=await load('vendor/loader/src/index.ts'),{default:Include}=await load('vendor/include/src/index.ts')
const row=(id:string,value=1)=>({id,name:'cordis:example',config:{value}})
const group=(id:string,config:any[])=>({id,name:'cordis:group',group:true,config})
const result:any={}
for(const mode of ['leaf','group','collision','member-collision','same-tree','positions','disabled']){
  const directory=resolve(dirname(input),'files/source',mode);await mkdir(directory,{recursive:true})
  let left:any[]=mode==='group'||mode==='member-collision'?[group('outer',[group('inner',[row('a')])])]:[row('a')]
  if(mode==='disabled')left[0].disabled=true
  const right=[group('g',mode==='collision'||mode==='member-collision'?[row('a',9)]:[])]
  if(mode==='same-tree'||mode==='positions')left=[row('a'),row('b'),group('g',[])]
  const paths=[resolve(directory,'left.json'),resolve(directory,'right.json')]
  for(const [index,data] of [left,right].entries())await writeFile(paths[index]!,JSON.stringify(data))
  const ctx=new Context();ctx.baseUrl=pathToFileURL(directory).href+'/'
  await ctx.plugin(Loader);ctx.loader.builtins.include=Include;ctx.loader.builtins.group=Group
  const calls:number[]=[];ctx.loader.builtins.example=(_ctx:any,config:any)=>{calls.push(config.value)}
  for(const [index,id] of ['L','R'].entries()){
    await ctx.loader.create({id,name:'cordis:include',config:{path:pathToFileURL(paths[index]!).href}});await ctx.loader.await()
  }
  await ctx.loader.await()
  const source=ctx.loader.store.L.subtree,target=ctx.loader.store.R.subtree
  const name=mode==='group'||mode==='member-collision'?'outer':'a',entry=source.store[name],member=source.store.a,oldFiber=member.fiber
  let error:string|null=null
  try{
    try{
      if(mode==='same-tree'){
        await source.update('a',{},'g',0);await source.update('a',{},null,-1)
      }else if(mode==='positions'){
        await source.create(row('c'),null,-1);await source.update('a',{},null,0);await source.update('c',{},'g',-10)
      }else await ctx.loader.update('L:'+name,mode==='leaf'?{config:{value:2}}:{},'R:g',0)
    }catch(exc:any){error=exc.message}
    await source.flush();await target.flush();await ctx.loader.await()
    const owner=['collision','member-collision','same-tree','positions'].includes(mode)?source:target
    result[mode]={error,files:await Promise.all(paths.map(async path=>JSON.parse(await readFile(path,'utf8')))),
      stores:[Object.keys(source.store).sort(),Object.keys(target.store).sort()],same_entry:owner.store[name]===entry,
      same_member:owner.store.a===member,same_fiber:member.fiber===oldFiber,entry_id:entry.id,calls,
      group_owner:entry.subgroup?entry.subgroup.tree===owner:null}
    if(mode==='group'){
      await ctx.loader.remove('R:outer');await target.flush();await ctx.loader.await()
      result[mode].removed=[Object.keys(target.store).sort(),JSON.parse(await readFile(paths[1]!,'utf8')),
        !member.fiber||member.fiber.state!==2]
    }
  }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(result))
