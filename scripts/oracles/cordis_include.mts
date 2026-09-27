import { Context } from '../../reference/vendor/cordis/src/index.ts'
import { Loader } from '../../reference/vendor/loader/src/index.ts'
import Include from '../../reference/vendor/include/src/index.ts'
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
  const entered = gate(), finish = gate()
  const directory = await mkdtemp(join(tmpdir(), 'cordis-include-'))
  const filename = join(directory, 'config.json')
  let include!: Include
  // Observe the real instance without replacing any Include behavior.
  class ObservedInclude extends Include {
    constructor(c: any, config: any) { super(c, config); include = this }
  }
  const write = (value: number) => writeFile(filename, JSON.stringify([
    { id: 'one', name: 'cordis:probe', config: { value } },
  ]), 'utf8')
  try {
    ctx.baseUrl = pathToFileURL(directory + '/').href
    await ctx.plugin(Loader).await()
    if ([48, 49, 50, 51].includes(id)) {
      const handle = ctx.plugin({ name: 'handle-lifecycle', inject: id >= 50 ? ['gate'] : [], apply(_c: any, config: any) {
        log.push('start:' + config.value)
        return () => { log.push('stop:' + config.value) }
      } }, { value: 1 })
      const raw = handle.ctx.fiber
      const target = id === 48 || id === 50 ? handle : raw
      if (id < 50) { await handle; await target.restart() }
      else { target.update({ value: 2 }); ctx.provide('gate', true); await target.await() }
      const observation = { log: [...log], states: [handle.state, raw.state], configs: [handle.config.value, raw.config.value] }
      await ctx.fiber.dispose()
      return { ...observation, finalLog: [...log], disposed: [handle.state, raw.state] }
    }
    if (id === 46 || id === 47) {
      const handle = ctx.plugin({ name: 'handle-recovery', apply(_c: any, config: any) {
        log.push(config.value)
        if (config.value === 'bad') throw new Error('bad config')
      } }, { value: 'bad' })
      const errorOf = async (operation: any) => { try { await operation; return null } catch (error: any) { return error.message } }
      const initial = await errorOf(handle)
      const raw = handle.ctx.fiber
      const target = id === 46 ? handle : raw
      target.update({ value: 'good' })
      const recovered = await errorOf(target.await())
      const original = await errorOf(handle)
      const methodError = await errorOf(handle.await())
      const observation = { initial, recovered, original, methodError, log: [...log],
        states: [handle.state, raw.state], configs: [handle.config.value, raw.config.value] }
      await ctx.fiber.dispose()
      return { ...observation, disposed: [handle.state, raw.state] }
    }
    if (id === 45) {
      const handle = ctx.plugin({ name: 'handle-identity', async apply(_c: any, config: any) {
        if (config.value === 2) { entered.release(); await finish.promise }
      } }, { value: 1 })
      const raw = await handle
      const identity = { same: handle === raw, contextOwnsRaw: handle.ctx.fiber === raw }
      const updating = handle.update({ value: 2 })
      await entered.promise
      const pending = { handle: handle.state, raw: raw.state }
      finish.release(); await updating
      await handle.dispose()
      return { identity, pending, final: { handle: handle.state, raw: raw.state } }
    }
    if (id === 44) {
      const fiber = await ctx.plugin({ name: 'public-dispose', apply() {
        return async () => { log.push('cleanup-enter'); entered.release(); await finish.promise; log.push('cleanup-exit') }
      } }).await()
      const first = fiber.dispose()
      await entered.promise
      let secondDone = false
      const second = Promise.resolve(fiber.dispose()).then(() => { secondDone = true; log.push('second-complete') })
      await new Promise(resolve => setTimeout(resolve, 50))
      const pending = { secondDone, log: [...log] }
      finish.release(); await Promise.all([first, second])
      return { pending, log, final: fiber.state }
    }
    if (id === 43) {
      ctx.loader.builtins.reject = { name: 'reject', apply(_c: any, config: any) {
        log.push('reject:' + config.value); throw new Error('rejected ' + config.value)
      } }
      await writeFile(filename, JSON.stringify([1, 2].map(value => ({
        id: 'row' + value, name: 'cordis:reject', config: { value },
      }))), 'utf8')
      const fiber = ctx.plugin(ObservedInclude, { path: pathToFileURL(filename).href })
      const errors = await fiber.await().then(() => [], error => error.errors.map((item: Error) => item.message))
      await include.await()
      const observation = { errors, state: fiber.state, data: (include as any).data ?? null,
        content: (include as any).content ?? null, rows: include.root.data, log: [...log] }
      await ctx.fiber.dispose()
      return { ...observation, final: fiber.state }
    }
    ctx.loader.builtins.probe = { name: 'probe', async apply(c: any, config: any) {
      const value = config.value
      log.push('start:' + value)
      if (value === ([39, 40, 41].includes(id) ? 1 : 2)) {
        entered.release(); await finish.promise
        if (id === 38 || id === 40) { log.push('reject:' + value); throw new Error('probe rejected ' + value) }
      }
      log.push('ready:' + value)
      return () => { log.push('stop:' + value) }
    } }
    await write(1)
    const fiber = ctx.plugin(ObservedInclude, { path: pathToFileURL(filename).href })
    if (id === 40) {
      const result = fiber.await().then(() => null, error => error.message)
      await entered.promise
      finish.release()
      const error = await result
      const observation = { error, state: fiber.state, data: (include as any).data ?? null,
        content: (include as any).content ?? null, rows: include.root.data, log: [...log] }
      await fiber.dispose()
      return { ...observation, final: fiber.state }
    }
    if (id === 41 || id === 42) {
      let operation: Promise<any>
      if (id === 42) {
        await fiber.await(); await write(2)
        operation = include.refresh()
      } else operation = fiber.await()
      const result = operation.then(() => null, error => error.message)
      await entered.promise
      let done = false
      const disposal = fiber.dispose().then(() => { done = true; log.push('dispose-complete') })
      await new Promise(resolve => setTimeout(resolve, 50))
      const pending = { done, log: [...log] }
      finish.release()
      const error = await result
      await disposal
      return { pending, error, final: fiber.state, log, entries: Object.keys(include.store) }
    }
    if (id === 39) {
      await entered.promise
      await write(2)
      const refresh = include.refresh()
      // Bounded observation window; final trace also verifies no overlapping apply.
      await new Promise(resolve => setTimeout(resolve, 50))
      const pending = [...log]
      finish.release()
      await Promise.all([fiber.await(), refresh])
      const after = [...log], committed = include.root.data[0]?.config.value
      await fiber.dispose()
      return { pending, after, committed, disposed: [...log] }
    }
    await fiber.await()
    await write(2)
    const first = include.refresh().then(() => null, error => error.message)
    await entered.promise
    await write(3)
    const second = include.refresh().then(() => null, error => error.message)
    const pending = [...log]
    finish.release()
    const errors = await Promise.all([first, second])
    const committed = include.root.data[0]?.config.value
    const after = [...log]
    await fiber.dispose()
    return { pending, after, errors, committed, disposed: [...log] }
  } finally {
    finish.release()
    await ctx.fiber.dispose()
    await rm(directory, { recursive: true, force: true })
  }
}
