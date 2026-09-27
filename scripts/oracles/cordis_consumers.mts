// Real Loader/HMR services. C33/C34 inject refresh triggers, not filesystem events.
import { Context } from '../../reference/vendor/cordis/src/index.ts'
import { Loader } from '../../reference/vendor/loader/src/index.ts'
import TimerService from '../../reference/vendor/timer/src/index.ts'
import Hmr from '../../reference/vendor/hmr/src/index.ts'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

function gate() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}
export async function scenario(id: number) {
  const ctx = new Context(), log: string[] = []
  const directory = await mkdtemp(join(tmpdir(), 'cordis-oracle-'))
  const finish = gate()
  try {
    ctx.baseUrl = pathToFileURL(directory + '/').href
    await ctx.plugin(Loader, { baseUrl: pathToFileURL(directory + '/').href }).await()
    const loader = ctx.loader
    if (id === 31 || id === 32) {
      const entered = gate()
      loader.builtins.probe = { name: 'probe', apply(c: any, config: any) {
        log.push('start:' + config.value)
        return async () => {
          log.push('stop:' + config.value)
          if (id === 32) { entered.release(); await finish.promise; log.push('cleaned') }
        }
      } }
      await loader.root.update([{ id: 'one', name: 'cordis:probe', config: { value: 1 } }])
      const entry = loader.store.one, options = entry.options
      if (id === 31) {
        await entry.update({ config: { value: 2 } })
        const observation = { sameEntry: loader.store.one === entry, sameOptions: entry.options === options,
          value: entry.options.config.value, owner: entry.fiber!.entry === entry, log: [...log] }
        await loader.root.remove('one')
        return { ...observation, after: [...log], removed: !loader.store.one }
      }
      const removing = loader.root.remove('one')
      await entered.promise
      const pending = { retained: loader.store.one === entry, detached: !entry.fiber, log: [...log] }
      finish.release(); await removing
      return { pending, log, removed: !loader.store.one }
    }
    await ctx.plugin(TimerService).await()
    const fiber = await ctx.plugin(Hmr, { root: ['.'], ignored: [], debounce: 10 }).await()
    const hmr: any = ctx.hmr
    const entered = gate(), second = gate()
    let count = 0
    const refresh = async () => {
      count++; log.push('enter:' + count)
      if (count === 1) { entered.release(); await finish.promise }
      log.push('exit:' + count)
    }
    if (id === 33 || id === 34) {
      const key = {}, other = {}, filename = join(directory, 'missing.json')
      hmr.refreshConfig(key, filename, refresh)
      await entered.promise
      hmr.refreshConfig(key, filename, refresh)
      hmr.refreshConfig(key, filename, refresh)
      if (id === 34) {
        hmr.refreshConfig(other, filename, async () => { log.push('other'); second.release() })
        await second.promise
      }
      const pending = [...log]
      finish.release()
      await Promise.all([...hmr.refreshTasks])
      return { pending, log, count }
    }
    const filename = join(directory, 'present.json')
    await writeFile(filename, '{}', 'utf8')
    // The public exact-path watcher performs its real initial scan.
    const unregister = await hmr.registerConfig(filename, refresh)
    await entered.promise
    if (id === 36) {
      const old = unregister()
      while (hmr.configs.size) await new Promise(resolve => setImmediate(resolve))
      await hmr.registerConfig(filename, () => { log.push('replacement'); second.release() })
      await second.promise
      const pending = { registrations: hmr.configs.size, log: [...log] }
      finish.release(); await old
      return { pending, log, registrations: hmr.configs.size }
    }
    let done = false
    const disposing = fiber.dispose().then(() => { done = true })
    while (!hmr.watcher.closed) await new Promise(resolve => setImmediate(resolve))
    const pending = { done, log: [...log] }
    finish.release(); await disposing
    return { pending, log, done, registrations: hmr.configs.size, removed: !ctx.get('hmr') }
  } finally {
    finish.release()
    await ctx.fiber.dispose()
    await rm(directory, { recursive: true, force: true })
  }
}
