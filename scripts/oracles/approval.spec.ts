/** Observe the actual pinned approval services; no substitute JS implementation. */
import { it, expect } from 'vitest'
import { writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import Approval from '@deepseek-ai/dsh-user-approval'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import Invariants from '@deepseek-ai/dsh-invariants'
import * as Companion from '@deepseek-ai/dsh-user-approval/invariant'
import { carrierKeyOf } from '@deepseek-ai/dsh-scope'

const drain = () => new Promise<void>(resolve => setTimeout(resolve, 0))
function audit(session: Session) {
  const events: any[] = session.events.filter(e => e.type.startsWith('approval/'))
  return events.map((event, index) => ({ type: event.type,
    data: { ...event.data, ...event.data.id !== undefined ? { id: '<uuid>' } : {} },
    ...event.data.id !== undefined ? { uuid: /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(event.data.id),
      paired: index === 0 || event.data.id === events[0].data.id } : {},
  }))
}

it('observes cancellation, policy ownership, and precommit audit pairing', async () => {
  const rows: any[] = []
  for (const mode of ['pre-aborted', 'never', 'abort-grant', 'abort-error', 'answer', 'missing']) {
    const ctx = new Context(), controller = new AbortController()
    await ctx.plugin(Approval, { policy: mode === 'never' ? 'never' : 'ask' })
    const session = Session.create(SessionId('probe-' + mode)), agent = { session } as any
    session.append('turn/start', { turn: 1 })
    const request = { agent, toolName: 'pwsh', signal: controller.signal }
    let calls = 0, borrowed = false, carrier = false, finish!: (answer: any) => void, reject!: (error: Error) => void, enter!: () => void
    const entered = new Promise<void>(resolve => { enter = resolve })
    if (mode !== 'missing') ctx.on('approval/request', function (req) {
      calls++; borrowed = req === request; carrier = carrierKeyOf(this) === agent
      if (mode.startsWith('abort-')) return new Promise<any>((resolve, fail) => { finish = resolve; reject = fail; enter() })
      return Promise.resolve('allowed-once')
    })
    if (mode === 'pre-aborted') controller.abort(null)
    const pending = ctx.approval.request(request)
    if (mode.startsWith('abort-')) { await entered; controller.abort('cancelled') }
    const outcome = await pending, before = audit(session)
    if (mode === 'abort-grant') finish('allowed-once')
    if (mode === 'abort-error') reject(new Error('late answer failed'))
    if (mode === 'answer') controller.abort()
    await drain()
    rows.push({ mode, outcome, calls, borrowed, carrier, before, after: audit(session) })
    await ctx.fiber.dispose()
  }
  {
    const ctx = new Context(), approval = await ctx.plugin(Approval)
    let prompt = await ctx.plugin(SystemPrompt)
    const session = Session.create(SessionId('prompt')), agent = { session } as any
    const text = async () => (await ctx.systemPrompt.assemble({ agent })).contexts.filter(e => e.name === 'approval:policy').map(e => e.text)
    const first = await text()
    await prompt.dispose(); prompt = await ctx.plugin(SystemPrompt)
    const reloaded = await text()
    await approval.dispose()
    rows.push({ mode: 'prompt-lifecycle', first, reloaded, disposed: await text(), serviceGone: ctx.get('approval') === undefined })
    await ctx.fiber.dispose()
  }
  {
    const ctx = new Context(); await ctx.plugin(Approval)
    const session = Session.create(SessionId('policy')), messages: any[] = []
    const agent = { session, inject: (message: any) => messages.push(message) } as any
    ctx.approval.setPolicy(agent, 'never'); ctx.approval.setPolicy(agent, 'never')
    rows.push({ mode: 'policy-notice', audit: audit(session), messages: messages.map(message => ({ ...message, id: '<message>', identified: typeof message.id === 'string' && message.id.length > 0 })) })
    await ctx.fiber.dispose()
  }
  {
    const ctx = new Context(); await ctx.plugin(SessionStore); await ctx.plugin(Invariants); await ctx.plugin(Companion)
    const session = ctx.sessions.create(SessionId('precommit'))
    session.append('turn/start', { turn: 1 })
    const remove = ctx.on('internal/dispatch', (_mode, name, args) => {
      if (name === 'session/event' && (args[1] as any).type === 'approval/asked') throw new Error('later veto')
    }, { global: true })
    let veto = ''
    try { session.append('approval/asked', { id: 'same' as any, toolName: 'pwsh' }) } catch (error: any) { veto = error.message }
    remove()
    session.append('approval/asked', { id: 'same' as any, toolName: 'pwsh' })
    let unmatched = ''
    try { session.append('approval/decided', { id: 'other' as any, outcome: 'rejected' }) } catch (error: any) { unmatched = error.message }
    session.append('approval/decided', { id: 'same' as any, outcome: 'cancelled' })
    rows.push({ mode: 'invariant-veto', veto, unmatched, events: session.events.map(e => ({ type: e.type, data: e.data })) })
    await ctx.fiber.dispose()
  }
  expect(rows).toHaveLength(9)
  if (process.env.APPROVAL_OUTPUT) await writeFile(process.env.APPROVAL_OUTPUT, JSON.stringify(rows, null, 2) + '\n')
})
