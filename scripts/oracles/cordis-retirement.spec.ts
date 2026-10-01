import { it } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { setup } from '../../reference/packages/extensions/cordis-host-runner/tests/helpers.ts'

const host = `return { async apply(ctx) {
  ctx.provide('probeValue', 'starting')
  harness.handle('read', args => args)
  await ctx.get('runnerGate').wait()
  ctx.provide('probeLate', 'ready')
} }`
const previous = `return { apply(ctx) { ctx.provide('probePrevious', 'ready') } }`

it('observes actual startup versus stop/removal ownership', async () => {
  const specs = JSON.parse(await readFile('scripts/oracles/cordis-retirement-cases.json', 'utf8'))
  const observations = []
  for (const spec of specs) {
    const { ctx, runner, gateway } = await setup()
    const owner: any = { id: 'owner', steer() {}, inject() {} }
    let enter!: () => void, release!: () => void
    const entered = new Promise<void>(resolve => { enter = resolve })
    const released = new Promise<void>(resolve => { release = resolve })
    ctx.provide('runnerGate', { async wait() { enter(); await released } })
    let activation: Promise<any> | undefined, ending: Promise<any> | undefined
    let defined: any, request: any
    const events = gateway.events
    const capture = () => ({ inventory: runner.inventory(),
      values: ['probePrevious', 'probeValue', 'probeLate'].map(name => ctx.get(name) ?? null),
      starting: (runner as any).starting.size, events: JSON.parse(JSON.stringify(events)) })
    try {
      if (spec.update) {
        defined = runner.define({ sessionId: owner.id, plugin: { kind: 'new', idPrefix: 'probe' }, name: 'Previous', purpose: 'retirement', code: { host: previous } } as any)
        await runner.run(owner, defined.pluginId, defined.packageId, 'run')
      }
      defined = runner.define({ sessionId: owner.id,
        plugin: defined ? { kind: 'existing', pluginId: defined.pluginId } : { kind: 'new', idPrefix: 'probe' },
        name: 'Probe', purpose: 'retirement', code: { host: spec.settled ? previous : host, ...(spec.client ? { client: 'return () => {}' } : {}) } } as any)
      if (spec.client) {
        await runner.run(owner, defined.pluginId, defined.packageId, spec.update ? 'update' : 'run')
        request = [...events].reverse().find(([name]) => name === 'cordis/request-run')![1] as any
        activation = runner.runHostHalf(owner, defined.pluginId, defined.packageId, request.mode, request.requestId, false)
      } else activation = runner.run(owner, defined.pluginId, defined.packageId, spec.update ? 'update' : 'run')
      if (spec.settled) await activation
      else await entered
      const before = capture()
      let endSettled = false
      ending = (spec.remove ? runner.undefine(owner, defined.pluginId) : runner.stop(owner, defined.pluginId)).then(value => { endSettled = true; return value })
      if (spec.settled) await ending
      await new Promise(resolve => setTimeout(resolve, 0))
      const during = { ...capture(), endSettled }
      release()
      const [started, ended] = await Promise.all([activation, ending])
      observations.push({ mode: spec.mode, before, during, started, ended, after: capture() })
    } finally { release(); await Promise.allSettled([activation, ending]); await ctx.fiber.dispose() }
  }
  await writeFile(process.env.CORDIS_RETIREMENT_OUTPUT!, JSON.stringify(observations, null, 2))
}, 60000)
