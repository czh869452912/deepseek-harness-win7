import { Context } from '../../reference/vendor/cordis/src/index.ts'
import { Loader } from '../../reference/vendor/loader/src/index.ts'
import Timer from '../../reference/vendor/timer/src/index.ts'
import Hmr from '../../reference/vendor/hmr/src/index.ts'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
export async function scenario(id: number) {
  if (id === 67) {
    const ctx = new Context(), log: string[] = [], directory = await mkdtemp(join(tmpdir(), 'hmr-settled-'))
    try {
      ctx.baseUrl = pathToFileURL(directory + '/').href
      await ctx.plugin(Loader, { baseUrl: pathToFileURL(directory + '/').href }).await()
      await ctx.plugin(Timer).await()
      await ctx.plugin(Hmr, { root: ['.'], ignored: [], debounce: 10 }).await()
      const hmr: any = ctx.hmr, key = {}, filename = join(directory, 'config.json')
      let count = 0, release!: () => void
      const checkpoint = new Promise<void>(r => release = r)
      function refresh() {
        log.push('refresh:' + ++count)
        if (count === 1) queueMicrotask(() => {
          log.push('running:' + Boolean(hmr.configRefreshes.get(key).running))
          hmr.refreshConfig(key, filename, refresh); hmr.refreshConfig(key, filename, refresh)
          release()
        })
      }
      hmr.refreshConfig(key, filename, refresh)
      await checkpoint
      await Promise.all([...hmr.refreshTasks])
      return { log }
    } finally { await ctx.fiber.dispose(); await rm(directory, { recursive: true, force: true }) }
  }
  const ctx = new Context(), log: string[] = []
  function prefix() { log.push('first'); queueMicrotask(() => log.push('checkpoint')) }
  if (id === 63) ctx.on('event', () => { prefix(); return undefined })
  if (id === 64) ctx.on('event', () => { prefix(); return Promise.resolve(undefined) })
  if (id === 65) ctx.on('event', async () => { prefix(); return undefined })
  if (id === 66) ctx.on('event', async () => { prefix(); throw new Error('rejected') })
  ctx.on('event', () => { log.push('second') })
  try { await ctx.serial('event'); log.push('returned') }
  catch { log.push('caught') }
  await Promise.resolve()
  await ctx.fiber.dispose()
  return { log }
}
