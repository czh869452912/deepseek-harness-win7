import { Context } from '../../reference/vendor/cordis/src/index.ts'
import { Loader } from '../../reference/vendor/loader/src/index.ts'
import Timer from '../../reference/vendor/timer/src/index.ts'
import Hmr from '../../reference/vendor/hmr/src/index.ts'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
export async function scenario(id: number) {
  const directory=await mkdtemp(join(tmpdir(),'cordis-complex-')), ctx=new Context(), log:string[]=[]
  const a=join(directory,'a.mjs'),b=join(directory,'b.mjs'),plugin=join(directory,'probe.mjs')
  try {
    await writeFile(a,"import { VALUE } from './b.mjs'; export function read() { return VALUE }")
    await writeFile(b,"import { read } from './a.mjs'; export const VALUE = 1")
    await writeFile(plugin,"import { read } from './a.mjs'; export default { name:'complex-probe', apply(c) {const v=read(),log=c.get('probeLog'); log.push('start:'+v); return ()=>log.push('stop:'+v) } }")
    ctx.baseUrl=pathToFileURL(directory+'/').href
    ctx.provide('probeLog',log)
    await ctx.plugin(Loader); await ctx.plugin(Timer); await ctx.plugin(Hmr,{root:[],ignored:[],debounce:10000})
    await ctx.loader.root.update([{id:'probe',name:pathToFileURL(plugin).href}])
    const old=ctx.loader.store.probe.fiber!.ctx.fiber, hmr:any=ctx.hmr
    await writeFile(b,"import { read } from './a.mjs'; export const VALUE = 2")
    hmr.stashed.add(pathToFileURL(b).href); await hmr.partialReload()
    for(const runtime of ctx.registry.values()) for(const fiber of runtime.fibers) await fiber.await()
    const result={log:[...log],replaced:ctx.loader.store.probe.fiber!.ctx.fiber!==old}
    await ctx.fiber.dispose()
    return {...result,finalLog:[...log]}
  } finally { await ctx.fiber.dispose(); await rm(directory,{recursive:true,force:true}) }
}
