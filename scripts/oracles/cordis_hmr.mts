import { Context } from '../../reference/vendor/cordis/src/index.ts'
import { Loader } from '../../reference/vendor/loader/src/index.ts'
import Timer from '../../reference/vendor/timer/src/index.ts'
import Hmr from '../../reference/vendor/hmr/src/index.ts'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
export async function scenario(id: number) {
  const directory = await mkdtemp(join(tmpdir(), 'cordis-module-')), ctx = new Context(), log: string[] = []
  const dependency = join(directory, 'dependency.mjs')
  const filename = join(directory, 'probe.mjs'), url = pathToFileURL(filename).href
  const source = (value: number, fail = false) => `export default { name: 'module-probe', apply(c) { const log=c.get('probeLog'); log.push('start:${value}'); ${fail ? "throw new Error('apply failed')" : `return () => log.push('stop:${value}')`} } }`
  try {
    ctx.baseUrl = pathToFileURL(directory + '/').href
    ctx.provide('probeLog', log)
    await ctx.plugin(Loader).await(); await ctx.plugin(Timer).await()
    await ctx.plugin(Hmr, { root: [], ignored: [], debounce: 10000 }).await()
    await writeFile(dependency, 'export const VALUE = 1', 'utf8')
    const initialSource = id >= 56 ? "import { VALUE } from './dependency.mjs';\n" + source(1).replaceAll("'start:1'", "'start:' + VALUE").replaceAll("'stop:1'", "'stop:' + VALUE") : source(1)
    await writeFile(filename, initialSource, 'utf8')
    await ctx.loader.root.update([{id:'probe',name:url}])
    const old = ctx.loader.store.probe.fiber!.ctx.fiber
    await writeFile(filename, id === 53 ? 'invalid syntax !!!' : source(2, id === 54), 'utf8')
    const hmr: any = ctx.hmr
    if (id >= 56) {
      await writeFile(filename, initialSource, 'utf8')
      await writeFile(dependency, id === 57 ? 'invalid syntax !!!' : 'export const VALUE = 2', 'utf8')
    }
    hmr.stashed.add(id >= 56 ? pathToFileURL(dependency).href : url)
    let reloadEvents = 0
    ctx.on('hmr/reload', () => { reloadEvents++ })
    await hmr.partialReload()
    for (const fiber of ctx.registry.values().flatMap((runtime: any) => runtime.fibers)) { try { await fiber.await() } catch {} }
    if (id === 55) {
      await writeFile(filename, source(3), 'utf8'); hmr.stashed.add(url); await hmr.partialReload()
      for (const runtime of ctx.registry.values()) for (const fiber of runtime.fibers) await fiber.await()
    }
    const current = ctx.loader.store.probe.fiber!
    const observation = {log:[...log], same:current.ctx.fiber === old, state:current.state, reloadEvents}
    await ctx.fiber.dispose()
    return {...observation, finalLog:[...log]}
  } finally { await ctx.fiber.dispose(); await rm(directory,{recursive:true,force:true}) }
}
