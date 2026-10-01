import { it } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { setup } from '../../reference/packages/extensions/cordis-host-runner/tests/helpers.ts'

const CLIENT = 'return () => {}'
const HOST = `return { apply(ctx) { ctx.provide('probeValue', 'ready'); harness.handle('read', args => args) } }`
const WAITING = `return { inject: ['runnerDependency'], apply(ctx) { harness.handle('read', args => args) } }`
const REPLACE = `return { apply(ctx) { const old = harness.handle('read', () => 'old'); harness.handle('read', args => args); old() } }`
const FAIL = `return { apply(ctx) { throw 'fixture apply failure' } }`
const GATE = `return { async apply(ctx) { await ctx.get('runnerGate').wait(); ctx.provide('probeValue', 'ready') } }`
const ERRORS = `return { apply(ctx) {
  harness.handle('a\\u0000b', () => { const error = new Error('c'); error.stack = 'fixture stack'; throw error })
  harness.handle('a', () => { const error = new Error('b\\u0000c'); error.stack = 'fixture stack'; throw error })
} }`
const detached = (value: any) => JSON.parse(JSON.stringify(value))

export async function observe(spec: any) {
  const { ctx, runner, gateway } = await setup()
  const events = gateway.events, steered: any[] = [], injected: any[] = []
  const message = (value: any) => { const { id, ...rest } = value; if (typeof id !== 'string') throw new Error('missing message identity'); return rest }
  const owner: any = { id: 'owner', steer: (value: any) => steered.push(message(value)), inject: (value: any) => injected.push(message(value)) }
  const foreign: any = { id: 'foreign', steer() {}, inject() {} }
  const impostor: any = { ...owner }
  ctx.provide('agents', new Map([['owner', owner], ['foreign', foreign]]))
  let enter!: () => void, release!: () => void, pending: Promise<any> | undefined
  const entered = new Promise<void>(resolve => { enter = resolve }), released = new Promise<void>(resolve => { release = resolve })
  ctx.provide('runnerGate', { async wait() { enter(); await released } })
  const saved: any = {}, rows: any[] = []
  let defined: any, lastHalf: any, request: any
  function refs(value: any): any {
    if (typeof value === 'string' && value.startsWith('$')) return value.slice(1).split('.').reduce((v, k) => v[k], saved)
    if (Array.isArray(value)) return value.map(refs)
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, v]) => [key, refs(v)]))
    return value
  }
  try {
    for (const raw of spec.steps) {
      const step = refs(raw), agent = step.agent === 'foreign' ? foreign : step.agent === 'impostor' ? impostor : owner
      const before = [events.length, steered.length, injected.length]
      let value: any
      try {
        const pid = defined?.pluginId, pkg = defined?.packageId
        switch (step.op) {
          case 'define': {
            const code: any = {}
            if (step.program !== 'client') code.host = step.program === 'waiting' ? WAITING : step.program === 'errors' ? ERRORS : step.program === 'replace' ? REPLACE : step.program === 'fail' ? FAIL : step.program === 'gate' ? GATE : HOST
            if (step.program === 'dual' || step.program === 'client' || step.program === 'waiting') code.client = CLIENT
            defined = runner.define({ sessionId: owner.id, plugin: step.existing ? { kind: 'existing', pluginId: pid } : { kind: 'new', idPrefix: 'probe' }, name: 'Probe', purpose: 'actual lifecycle', code } as any)
            value = defined; break
          }
          case 'reference': value = runner.reference(agent, pid); break
          case 'run': { const controller = new AbortController(); if (step.aborted) controller.abort('fixture abort'); value = await runner.run(agent, pid, pkg, step.mode, controller.signal); break }
          case 'begin': pending = runner.run(agent, pid, pkg, 'run'); await entered; value = null; break
          case 'release': release(); value = null; break
          case 'join': value = await pending; break
          case 'request': request = [...events].reverse().find(([name]) => name === 'cordis/request-run')![1]; value = request; break
          case 'half': lastHalf = await runner.runHostHalf(agent, pid, pkg, step.mode ?? (step.direct ? 'run' : request.mode), step.direct ? null : (request as any).requestId, step.future ?? false); value = lastHalf; break
          case 'clientCode': value = runner.getClientCode(agent, pid, step.runId ?? lastHalf.pluginRunId); break
          case 'resolve': value = await runner.resolveRequestRun(request.requestId, step.resolution); break
          case 'resolveRace': value = await Promise.all([runner.resolveRequestRun(request.requestId, step.resolution), runner.resolveRequestRun(request.requestId, step.resolution)]); break
          case 'settle': value = await runner.settleUserRun(agent, pid, step.resolution); break
          case 'stop': value = await runner.stop(agent, pid); break
          case 'undefine': value = await runner.undefine(agent, pid); break
          case 'panelStop': value = await runner.stopFromPanel(agent, pid); break
          case 'panelDelete': value = await runner.undefineFromPanel(agent, pid); break
          case 'provide': ctx.provide('runnerDependency', {}); await new Promise(resolve => setTimeout(resolve, 10)); value = null; break
          case 'invoke': value = await runner.invoke(pid, runner.inventory()[0]?.activeRun?.pluginRunId ?? 'stale', step.method, step.args); break
          case 'guard': value = await runner.reportClientGuardFailure(agent, pid, step.runId ?? lastHalf.pluginRunId, step.failure); break
          case 'render': value = await runner.reportRenderFailure(agent, pid, step.runId ?? lastHalf.pluginRunId, step.failure); break
          default: throw new Error('unknown operation ' + step.op)
        }
        if (step.save) saved[step.save] = value
        value ??= null
      } catch (error: any) { value = { error: { message: error.message } } }
      const grants = (runner as any).registry.all().map((plugin: any) => ({ pluginId: plugin.pluginId, approved: [...plugin.approvedClientPackages].sort(), future: plugin.clientVersionUpdatesApproved }))
      rows.push(detached({ op: step.op, value, inventory: runner.inventory(), grants,
        events: events.slice(before[0]), steer: steered.slice(before[1]), inject: injected.slice(before[2]), provided: ctx.get('probeValue') ?? null }))
    }
    // Normalize only checkout location in original stack frames; retain every
    // message, frame and coordinate. Python has its own exception lifecycle.
    if (spec.mode === 'actual-host-apply-failure-and-retry') {
      const visit = (value: any) => {
        if (!value || typeof value !== 'object') return
        for (const [key, child] of Object.entries(value)) {
          if (key === 'stack' && typeof child === 'string') value[key] = child.split(process.cwd().replaceAll('\\', '/')).join('[workspace]')
          else visit(child)
        }
      }
      visit(rows)
    }
    return { mode: spec.mode, rows }
  } finally { release(); if (pending) await pending; await ctx.fiber.dispose() }
}

it('records actual pinned runner state and Host lifecycle', async () => {
  const specs = JSON.parse(await readFile('scripts/oracles/cordis-runner-cases.json', 'utf8'))
  const cases = []
  for (const spec of specs) cases.push(await observe(spec))
  await writeFile(process.env.CORDIS_RUNNER_OUTPUT!, JSON.stringify(cases, null, 2))
}, 60000)
