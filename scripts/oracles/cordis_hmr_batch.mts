import { Context } from '../../reference/vendor/cordis/src/index.ts'
import { Loader } from '../../reference/vendor/loader/src/index.ts'
import Timer from '../../reference/vendor/timer/src/index.ts'
import Hmr from '../../reference/vendor/hmr/src/index.ts'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
export async function scenario(id:number) {
 const dir=await mkdtemp(join(tmpdir(),'cordis-batch-')),ctx=new Context(),log:string[]=[]
 const source=(label:string,value:number)=>`export default {name:'probe-${label}',apply(c){const log=c.get('probeLog');log.push('start:${label}:${value}');return ()=>log.push('stop:${label}:${value}')}}`
 try {
  ctx.baseUrl=pathToFileURL(dir+'/').href;ctx.provide('probeLog',log)
  await ctx.plugin(Loader);await ctx.plugin(Timer);await ctx.plugin(Hmr,{root:[],ignored:[],debounce:10000})
  const rows:any[]=[]
  for(const label of ['a','b']) { const filename=join(dir,label+'.mjs');await writeFile(filename,source(label,1));rows.push({id:label,name:pathToFileURL(filename).href});await ctx.loader.root.update([...rows]) }
  const hmr:any=ctx.hmr
  for(const label of ['a','b']) {const filename=join(dir,label+'.mjs');await writeFile(filename,label==='b'?'invalid syntax !!!':source(label,2));hmr.stashed.add(pathToFileURL(filename).href)}
  await hmr.partialReload()
  for(const runtime of ctx.registry.values()) for(const fiber of runtime.fibers) await fiber.await()
  const result={log:[...log]};await ctx.fiber.dispose();return {...result,finalLog:[...log]}
 } finally {await ctx.fiber.dispose();await rm(dir,{recursive:true,force:true})}
}
