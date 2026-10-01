// Construct real Agent lifetimes; no replacement driver or maintenance implementation.
import { it } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import Llm, { createUserMessage, errorChain } from '@deepseek-ai/dsh-llm'
import Sessions, { SessionId } from '@deepseek-ai/dsh-session'
import Tools from '@deepseek-ai/dsh-tools'
import Prompt from '@deepseek-ai/dsh-system-prompt'
import Agents from '@deepseek-ai/dsh-agent'
import Loop from '@deepseek-ai/dsh-agent-loop'
import TokenMeter from '@deepseek-ai/dsh-token-meter'
import BasicCompactionEngine from '@deepseek-ai/dsh-compaction-basic'

const tick = () => new Promise<void>(resolve => setTimeout(resolve, 0))
async function compaction(spec: any): Promise<any> {
  const ctx = new Context()
  await ctx.plugin(Llm); await ctx.plugin(Sessions); await ctx.plugin(Tools)
  await ctx.plugin(Prompt); await ctx.plugin(Agents); await ctx.plugin(Loop, { agents: [] })
  await ctx.plugin(TokenMeter)
  const handle = await ctx.agents.create({ sessionId: SessionId(spec.mode), options: {} })
  const agent = handle.agent
  const reached = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
  const markers: string[] = []
  let operationSignal: AbortSignal
  let flushes = 0
  let retainedInJob = false
  agent.ctx.effect(() => () => { markers.push('released') })
  class Engine extends BasicCompactionEngine {
    protected override async summarize(_input: any, _agent: any, signal?: AbortSignal): Promise<any> {
      operationSignal = signal!
      if (spec.stage === 'summary') { reached.resolve(); await release.promise; retainedInJob = markers.length === 0 }
      return { summary: [{ type: 'text', text: 'checkpoint' }], provider: 'probe', model: 'model' }
    }
  }
  const engine = new Engine(ctx, { auto: false })
  agent.session.append('user/message', createUserMessage({ content: [{ type: 'text', text: 'important facts '.repeat(300) }], source: { kind: 'user' } }), { surfaceOp: 'append' })
  agent.session.append('user/message', createUserMessage({ content: [{ type: 'text', text: 'recent question' }], source: { kind: 'user' } }), { surfaceOp: 'append' })
  ctx.sessions.flush = async () => {
    flushes++
    if (spec.stage === 'flush') { reached.resolve(); await release.promise }
    retainedInJob = markers.length === 0
    return true
  }
  const caller = new AbortController(), callerCause = 'reason' in spec ? spec.reason : { kind: 'user' }, agentCause = { kind: 'parent' }
  const operation = engine.compactNow(agent, caller.signal).then(
    () => ({ code: 'unexpected-success', callerReason: false }),
    error => ({ code: error.code ?? null, callerReason: error === callerCause, rendered: errorChain(error) }))
  await reached.promise
  let disposed = false
  let disposal: Promise<void> | undefined
  if (spec.action === 'dispose') disposal = handle.dispose().then(() => { disposed = true })
  else if (spec.action === 'agent-first') { agent.cancel(agentCause as any); caller.abort(callerCause) }
  else { caller.abort(callerCause); agent.cancel((spec.action === 'shared-cause' ? callerCause : agentCause) as any) }
  await tick()
  const before = { pending: !disposed, retained: markers.length === 0,
    registered: ctx.agents.get(agent.id) === agent && ctx.sessions.get(agent.id) === agent.session,
    aborted: operationSignal!.aborted }
  release.resolve()
  const outcome = await operation
  if (disposal) await disposal
  else await handle.dispose()
  const row = { mode: spec.mode, before, outcome, retainedInJob, flushes,
    released: markers, clean: ctx.agents.get(agent.id) === undefined && ctx.sessions.get(agent.id) === undefined,
    generation: agent.session.surface.replaceGeneration,
    failedEnds: agent.session.events.filter(e => e.type === 'compaction/end' && e.data.error !== undefined).map(e => e.data.error),
    events: agent.session.events.filter(e => e.type.startsWith('compaction/')).map(e => ({ type: e.type, failed: 'error' in e.data })) }
  await ctx.fiber.dispose()
  return row
}
it('observes maintenance ownership, cancellation and driver handover', async () => {
  const cases = JSON.parse(await readFile('scripts/oracles/maintenance-cases.json', 'utf8'))
  const rows: any[] = []
  for (const spec of cases) {
    if (spec.kind === 'compaction') { rows.push(await compaction(spec)); continue }
    const ctx = new Context()
    await ctx.plugin(Llm); await ctx.plugin(Sessions); await ctx.plugin(Tools)
    await ctx.plugin(Prompt); await ctx.plugin(Agents); await ctx.plugin(Loop, { agents: [] })
    const handle = await ctx.agents.create({ sessionId: SessionId(spec.mode), options: {} })
    const agent = handle.agent
    const reached = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
    const turnReached = Promise.withResolvers<void>(), turnRelease = Promise.withResolvers<void>()
    const claims: string[] = []
    ctx.on('agent/pre-step', async ({ messages }) => {
      for (const message of messages) for (const block of message.content) {
        if (block.type === 'text') claims.push(block.text)
      }
      turnReached.resolve(); await turnRelease.promise
      return { kind: 'reject' as const }
    })
    const send = (text: string, wake = true) => {
      const message = createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'user' } })
      if (wake) agent.followup(message); else agent.inject(message)
      return message.id
    }
    if (spec.idleCancel) { send('parked', false); agent.cancel({ kind: 'user' }, { keepInbox: true }) }
    const failure = new Error('job failed')
    let signal: AbortSignal
    const operation = agent.runMaintenance(async current => {
      signal = current; reached.resolve(); await release.promise
      if (spec.error) throw failure
      return 42
    })
    const reserved = agent.status === 'idle'
    let busy = false
    try { agent.runMaintenance(async () => 0) } catch { busy = true }
    const outcome = operation.then(value => ({ value }), error => ({ sameFailure: error === failure }))
    await reached.promise
    let idleSettled = false
    const idle = agent.whenIdle().then(() => { idleSettled = true })
    await tick()
    const waitsMaintenance = !idleSettled
    const first = { kind: spec.cancel ?? 'user' } as any
    let wakeId: any
    if (spec.wake) wakeId = send('queued')
    if (spec.inject) send('injected', false)
    if (spec.remove) agent.inbox.remove(wakeId)
    if (spec.cancel) agent.cancel(first, { keepInbox: spec.keep === true })
    if (spec.secondCancel) agent.cancel({ kind: 'disposed' }, { keepInbox: true })
    if (spec.afterWake) send('after cancel')
    const cancellation = { aborted: signal!.aborted, firstReason: signal!.aborted && signal!.reason === first }
    release.resolve()
    const result = await outcome
    const expectTurn = (spec.wake && !spec.remove && (!spec.cancel || spec.keep))
      || (spec.afterWake && spec.cancel !== 'disposed')
    let waitsDriver = false
    if (expectTurn) { await turnReached.promise; await tick(); waitsDriver = !idleSettled }
    turnRelease.resolve(); await idle
    rows.push({ mode: spec.mode, reserved, busy, waitsMaintenance, waitsDriver,
      cancellation, outcome: result, claims, status: agent.status,
      queued: agent.inbox.nextTurn.length + agent.inbox.nextStep.length,
      turns: agent.session.events.filter(e => e.type === 'turn/start' || e.type === 'turn/end').map(e => e.type) })
    await handle.dispose(); await ctx.fiber.dispose()
  }
  await writeFile(process.env.MAINTENANCE_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
}, 15000)
