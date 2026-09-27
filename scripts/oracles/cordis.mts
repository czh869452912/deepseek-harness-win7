// Observation-only adapter: no assertions, patched upstream, or sorted events.
import { Context, Service } from '../../reference/vendor/cordis/src/index.ts'
import TimerService from '../../reference/vendor/timer/src/index.ts'

const id = Number(process.argv[2])
const ctx = new Context()
const log: any[] = []
function plugin(name: string, apply: any, inject: string[] = []) {
  return { name, apply, inject }
}
function gate() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}
const absent = (value: any) => value === undefined ? null : value
const copy = (value: any) => JSON.parse(JSON.stringify(value))
async function loaded(p: any) {
  return await ctx.plugin(p).await()
}

async function scenario(): Promise<any> {
  if (id >= 37) return (await import('./cordis_include.mts')).scenario(id)
  if (id >= 31) return (await import('./cordis_consumers.mts')).scenario(id)
  if (id === 1) {
    const f = await loaded(plugin('provider', c => c.provide('svc', { v: 1 })))
    const before = [f.state, ctx.get('svc')]
    await f.dispose()
    return { before, after: [f.state, absent(ctx.get('svc'))] }
  }
  if (id === 2) {
    const f = await loaded(plugin('async-effect', async () => {
      await Promise.resolve(); log.push('setup')
      return () => { log.push('dispose') }
    }))
    const before = copy(log); await f.dispose()
    return { before, after: log }
  }
  if (id === 3 || id === 21) {
    const entered = gate(), finish = gate()
    const f = ctx.plugin(plugin('loading', async c => {
      c.provide('svc', 'value'); entered.release(); await finish.promise
    }))
    await entered.promise
    const pending = [f.state, absent(ctx.get('svc')), ctx.get('svc', false), ctx['svc']]
    finish.release(); await f.await()
    const active = [f.state, ctx.get('svc')]; await f.dispose()
    return { pending, active }
  }
  if (id === 4 || id === 5) {
    const events: any[] = []
    ctx.on('internal/status', (f, old) => { events.push([f.name, old, f.state]) })
    const consumer = ctx.plugin(plugin('consumer', () => {
      log.push('apply'); return () => { log.push('dispose') }
    }, ['svc']))
    const pending = consumer.state
    const provider = await loaded(plugin('provider', c => c.provide('svc', 1)))
    await consumer.await(); const active = consumer.state
    await provider.dispose(); await consumer.await()
    return { pending, active, final: consumer.state, log, events }
  }
  if (id === 6) {
    ctx.on('internal/plugin', f => {
      if (f.name === 'pending' && f.uid !== null) f.ctx.effect(() => () => { log.push('drained') }, 'observer')
    })
    const f = ctx.plugin(plugin('pending', () => { log.push('unexpected') }, ['missing']))
    const before = f.state; await f.dispose()
    return { before, final: f.state, log }
  }
  if (id === 7) {
    const f = await loaded(plugin('updatable', (c, config) => {
      log.push(['apply', config])
      c.on('internal/update', (cfg, noSave, next) => { log.push(['hook', cfg, noSave]); return next() })
      return () => { log.push(['dispose']) }
    }))
    await f.update({ n: 2 }); await f.await()
    f.ctx.on('internal/update', () => { log.push(['veto']) })
    await f.update({ n: 3 }); await f.await()
    return { log, config: f.config, state: f.state }
  }
  if (id === 8) {
    ctx.on('internal/get', (c, name, error, next) => {
      log.push(name); return name === 'virtual' ? 'intercepted' : next()
    })
    ctx.provide('declared', 'value')
    const root = ctx.get('declared'), seen: any = {}
    await loaded(plugin('reader', c => {
      seen.attribute = c.declared; seen.virtual = c.virtual; seen.get = c.get('declared')
    }, ['declared']))
    return { root, seen, log }
  }
  if (id === 9) {
    const d = ctx.on('event', () => {})
    const before = ctx.fiber.getEffects()
    const first = absent(d()), second = absent(d())
    const after = ctx.fiber.getEffects()
    ctx.effect(() => undefined)
    return { before, first, second, after, anonymous: ctx.fiber.getEffects() }
  }
  if (id === 10) {
    const outer = ctx.effect(() => ctx.effect(() => () => { log.push('nested-disposed') }, 'inner'), 'outer')
    const before = copy(ctx.fiber.getEffects())
    const dispose = await outer; await dispose()
    return { before, after: ctx.fiber.getEffects(), log }
  }
  if (id === 11 || id === 15 || id === 20) {
    let body: any = () => () => { log.push('disposed') }
    if (id === 15) body = function* () { yield () => { log.push('first') }; yield () => { log.push('second') } }
    if (id === 20) body = async function* () { yield () => { log.push('first') }; await Promise.resolve(); yield () => { log.push('second') } }
    const f = await loaded(plugin('effects', body))
    const before = [f.state, f.getEffects()]; await f.dispose()
    return { before, log, final: f.state }
  }
  if (id === 12) {
    const entered = gate(), finish = gate()
    const provider = await loaded(plugin('provider', c => c.provide('svc', 1)))
    const consumer = await loaded(plugin('consumer', c => {
      c.effect(() => async () => { log.push('cleanup-enter'); entered.release(); await finish.promise; log.push('cleanup-exit') }, 'cleanup')
    }, ['svc']))
    const disposal = provider.dispose()
    const immediate = copy(log)
    await entered.promise
    const pending = { log: copy(log), visible: absent(ctx.get('svc')), ownerRetains: !!provider.store?.svc }
    finish.release(); await disposal
    return { immediate, pending, log, final: consumer.state, ownerRetains: !!provider.store?.svc }
  }
  if (id === 13) {
    const f = await loaded(plugin('dispose', c => { c.effect(() => () => { log.push('unloaded') }, 'cleanup') }))
    const pending = f.dispose()
    const immediate = { uidCleared: f.uid === null, log: copy(log), awaitable: typeof pending?.then === 'function' }
    await pending
    return { immediate, final: f.state, log }
  }
  if (id === 14) {
    let disposal: any
    ctx.on('internal/status', (f, old) => { if (f.name === 'reentrant' && old === 0) disposal = f.dispose() })
    const f = ctx.plugin(plugin('reentrant', () => { log.push('applied') }))
    const immediate = { log: copy(log), uidCleared: f.uid === null, state: f.state }
    await disposal; await f.await()
    return { immediate, log, final: f.state }
  }
  if (id === 16) {
    const d = ctx.effect(async () => { await Promise.resolve(); throw new Error('setup failed') }, 'failed')
    let awaited = '', called = ''
    try { await d } catch (e: any) { awaited = e.message }
    const finish = gate()
    const pending = ctx.effect(async () => { await finish.promise; throw new Error('gated failed') }, 'gated')
    finish.release()
    try { await pending() } catch (e: any) { called = e.message }
    return { awaited, called, effects: ctx.fiber.getEffects() }
  }
  if (id === 17) {
    class S extends Service {
      Config = { merge: (...configs: any[]) => { log.push(configs); return Object.assign({}, ...configs) } }
      constructor(c: any) { super(c, 'svc') }
    }
    const leaf = ctx.intercept('svc', { root: 1 }).intercept('svc', { mid: 2 }).extend()
    const service = new S(leaf)
    return { merged: service[Service.resolveConfig](), inputs: log }
  }
  if (id === 18) {
    ctx.on('ok', () => 'ignored')
    const result = absent(await ctx.parallel('ok'))
    ctx.on('fail', () => { throw new Error('listener failed') })
    let errors: string[] = []
    try { await ctx.parallel('fail') } catch (e: any) { errors = e.errors.map(x => x.message) }
    return { result, errors }
  }
  if (id === 19) {
    ctx.on('event', () => { log.push(1); return undefined })
    ctx.on('event', () => { log.push(2); return 'stop' })
    ctx.on('event', () => { log.push(3); return 'unreachable' })
    const result = ctx.bail('event')
    ctx.on('false', () => false); ctx.on('false', () => 'value')
    ctx.on('async', async () => 'async')
    const pending = ctx.bail('async')
    return { result, log, afterFalse: ctx.bail('false'), awaitable: typeof pending.then === 'function', resolved: await pending }
  }
  if (id === 22) {
    const finish = gate(), doneA = gate(), doneB = gate()
    ctx.on('event', async () => { log.push('a-prefix'); await finish.promise; log.push('a-tail'); doneA.release() })
    ctx.on('event', () => { log.push('sync') })
    ctx.on('event', async () => { log.push('b-prefix'); await finish.promise; log.push('b-tail'); doneB.release() })
    ctx.emit('event'); const immediate = copy(log)
    finish.release(); await Promise.all([doneA.promise, doneB.promise])
    return { immediate, log }
  }
  if (id === 23) {
    ctx.on('event', () => { log.push('first'); throw new Error('sync failure') })
    ctx.on('event', () => { log.push('unreachable') })
    let error = ''
    try { ctx.emit('event') } catch (e: any) { error = e.message }
    return { error, log }
  }
  if (id === 24) {
    const reported = gate()
    const errors: string[] = []
    process.once('unhandledRejection', (error: any) => { errors.push(error.message); reported.release() })
    ctx.on('event', async () => { log.push('prefix'); throw new Error('async failure') })
    ctx.on('event', () => { log.push('peer') })
    ctx.emit('event'); const immediate = copy(log)
    await reported.promise
    return { immediate, log, errors }
  }
  if (id === 25 || id === 27 || id === 30) {
    const entered = gate(), finish = gate()
    let release!: () => any
    const f = await loaded(plugin('owner', c => {
      release = c.effect(() => async () => { log.push('cleanup-enter'); entered.release(); await finish.promise; log.push('cleanup-exit') }, 'resource')
    }))
    const first = id === 30 ? f.dispose() : release()
    await entered.promise
    let cancellation: string | null = null
    if (id === 30) {
      // Abandon one observer without cancelling the owned Promise operation.
      const aborted = Promise.reject(new Error('observer cancelled'))
      try { await Promise.race([first, aborted]) } catch { cancellation = 'observer cancelled' }
    }
    const repeated = id === 30 ? f.dispose() : release()
    let ownerDone = false
    const owner = Promise.resolve(id === 27 || id === 30 ? ctx.fiber.dispose() : f.dispose()).then(() => { ownerDone = true })
    const pending = { log: copy(log), ownerDone }
    finish.release(); await Promise.all([first, repeated, owner])
    return { pending, log, ownerDone, cancellation }
  }
  if (id === 26) {
    const entered = gate(), finish = gate()
    const f = ctx.plugin(plugin('iterator', async function* () {
      yield () => { log.push('first-disposed') }
      entered.release(); await finish.promise
      yield () => { log.push('late-disposed') }
      log.push('unreachable-next')
    }))
    await entered.promise
    const disposal = f.dispose(); const immediate = copy(log)
    finish.release(); await disposal
    return { immediate, log, final: f.state }
  }
  if (id === 28 || id === 29) {
    await ctx.plugin(TimerService).await()
    let operation: Promise<any>
    const f = await loaded(plugin('timer-owner', c => {
      if (id === 28) operation = c.timeout(60000)
      else operation = c.interval(60000).next()
    }, ['timer']))
    // Attach a rejection handler before owner disposal, so this is observed.
    const result = operation!.then(() => 'unexpected-resolution', e => e.message)
    await f.dispose()
    return { result: await result, effects: f.getEffects(), final: f.state }
  }
  throw new Error('Unknown scenario: ' + id)
}

scenario().then(value => {
  console.log(JSON.stringify({ case: `C${id}`, observation: value }))
}, error => { console.error(error); process.exitCode = 1 })
