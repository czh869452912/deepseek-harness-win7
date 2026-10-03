import { writeFileSync } from 'node:fs'
import { expect, it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import LlmRuntime, { createUserMessage } from '@deepseek-ai/dsh-llm'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime, { defineContentToolFixture } from '@deepseek-ai/dsh-tools'
import AgentRegistry from '@deepseek-ai/dsh-agent'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { MockAdapter, textResponse, toolCallResponse } from '../../reference/packages/core/agent-loop/tests/mock-adapter.ts'

async function harness(script: any[]) {
  const ctx = new Context()
  for (const plugin of [LlmRuntime, SessionStore, SystemPrompt, ToolRuntime, AgentRegistry]) await ctx.plugin(plugin)
  await ctx.plugin(AgentLoop, {agents: []})
  const adapter = new MockAdapter(script)
  ctx.llm.registerAdapter(['mock'], adapter)
  const handle = await ctx.agents.create({sessionId: SessionId('signal-owner'), agentOptions: {provider: 'mock', model: 'fixture'}})
  return {ctx, adapter, handle}
}

it('observes original model/tool abort generations and cancellation containment', async () => {
  const observations: any = {}
  const cause = {kind: 'user', detail: 'actual cancellation reason'} as const
  const first = await harness([toolCallResponse('signal-first', 'signal_probe', {}),
    toolCallResponse('signal-next', 'signal_probe', {}), textResponse('next turn completed')])
  const signals: AbortSignal[] = []
  const notifications: any[] = []
  const ready = Promise.withResolvers<void>()
  first.ctx.tools.register(defineContentToolFixture({name: 'signal_probe', description: 'cancellation consumer',
    parameters: {}, execute: async (_args, execution) => {
      const signal = execution.signal
      signals.push(signal)
      const cancelled = () => {notifications.push(signal.reason)}
      signal.addEventListener('abort', cancelled, {once: true})
      try {
        if (signals.length === 1) {
          ready.resolve()
          await new Promise<void>(resolve => {signal.addEventListener('abort', () => {resolve()}, {once: true})})
        }
        return [{type: 'text', text: 'signal generation consumed'}]
      } finally {signal.removeEventListener('abort', cancelled)}
    }}))
  try {
    first.handle.agent.followup(createUserMessage({content: 'first turn'}))
    await ready.promise
    const initiallyActive = !signals[0]!.aborted
    first.handle.agent.cancel(cause)
    await first.handle.agent.whenIdle()
    first.handle.agent.followup(createUserMessage({content: 'next turn'}))
    await first.handle.agent.whenIdle()
    observations.tools = {signalCount: signals.length, initiallyActive,
      firstAborted: signals[0]!.aborted, reason: signals[0]!.reason, notifications,
      nextDistinct: signals[1] !== signals[0], nextActive: !signals[1]!.aborted,
      modelRequests: first.adapter.requests.length,
      turnReasons: first.handle.agent.session.events.filter(event => event.type === 'turn/end').map(event => (event as any).data.reason)}
    expect(signals.length).toBe(2)
  } finally {await first.handle.dispose(); await first.ctx.fiber.dispose()}
  const second = await harness([textResponse('recovered after cancellation')])
  let initial = true
  second.handle.agent.ctx.on('agent/pre-step', (_payload, next) => {
    if (!initial) return next()
    initial = false
    second.handle.agent.cancel(cause)
    throw new Error('controlled failure after cancellation')
  })
  try {
    second.handle.agent.followup(createUserMessage({content: 'cancelled admission'}))
    await second.handle.agent.whenIdle()
    second.handle.agent.followup(createUserMessage({content: 'next admitted turn'}))
    await second.handle.agent.whenIdle()
    observations.admission = {status: second.handle.agent.status, modelRequests: second.adapter.requests.length,
      turnReasons: second.handle.agent.session.events.filter(event => event.type === 'turn/end').map(event => (event as any).data.reason)}
    expect(observations.admission.modelRequests).toBe(1)
  } finally {await second.handle.dispose(); await second.ctx.fiber.dispose()}
  const third = await harness([toolCallResponse('queued-first', 'queued_probe', {}), textResponse('first completed'),
    toolCallResponse('queued-next', 'queued_probe', {}), textResponse('second completed')])
  const queuedSignals: AbortSignal[] = []
  const queuedReady = Promise.withResolvers<void>()
  const release = Promise.withResolvers<void>()
  third.ctx.tools.register(defineContentToolFixture({name: 'queued_probe', description: 'queued consumer', parameters: {},
    execute: async (_args, execution) => {
      queuedSignals.push(execution.signal)
      if (queuedSignals.length === 1) {queuedReady.resolve(); await release.promise}
      return [{type: 'text', text: 'queued tool consumed'}]
    }}))
  try {
    third.handle.agent.followup(createUserMessage({content: 'first queued turn'}))
    await queuedReady.promise
    third.handle.agent.followup(createUserMessage({content: 'second queued turn'}))
    release.resolve()
    await third.handle.agent.whenIdle()
    observations.queued = {signalCount: queuedSignals.length, sameSignal: queuedSignals[0] === queuedSignals[1],
      active: queuedSignals.every(signal => !signal.aborted), modelRequests: third.adapter.requests.length,
      turnReasons: third.handle.agent.session.events.filter(event => event.type === 'turn/end').map(event => (event as any).data.reason)}
    expect(queuedSignals.length).toBe(2)
  } finally {release.resolve(); await third.handle.dispose(); await third.ctx.fiber.dispose()}
  writeFileSync(process.env.AGENT_SIGNAL_OUTPUT!, JSON.stringify(observations, null, 2) + '\n')
}, 20000)
