import { it, expect } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import { LlmRuntime, LlmAdapter, createUserMessage, createMessage } from '@deepseek-ai/dsh-llm'
import TokenMeter from '@deepseek-ai/dsh-token-meter'
import BasicCompactionEngine from '@deepseek-ai/dsh-compaction-basic'
import { resolveConfig, resolveTargetPolicy, resolveCompactSpec } from '../../reference/packages/compaction/compaction-basic/src/config.ts'
import { compactSurfaceRegion } from '../../reference/packages/compaction/compaction-basic/src/region.ts'
import { ManualCompactionError } from '@deepseek-ai/dsh-compaction'

async function transaction(spec: any): Promise<any> {
  const ctx = new Context()
  try {
    await ctx.plugin(SessionStore)
    await ctx.plugin(TokenMeter)
    const session = ctx.sessions.create()
    session.append('user/message', createUserMessage({ content: [{ type: 'text', text: 'important facts '.repeat(300) }], source: { kind: 'user' } }), { surfaceOp: 'append' })
    session.append('user/message', createUserMessage({ content: [{ type: 'text', text: 'recent question' }], source: { kind: 'user' } }), { surfaceOp: 'append' })
    session.append('request/header', { header: { config: { provider: 'old', model: 'old-model' }, system: 'original prefix' }, reason: 'initial' })
    const manual = spec.manual !== false
    if (!manual) session.append('turn/start', { turn: 1 })
    const control = new AbortController()
    const reason = new Error('caller stopped')
    const inputs: any[] = []
    let flushes = 0
    const summarize = async (input: any, agent: any, signal: any): Promise<any> => {
      if (spec.action === 'header') session.append('request/header', { header: { config: { provider: 'new', model: 'new-model' }, system: 'changed prefix' }, reason: 'initial' })
      inputs.push({ keys: Object.keys(input).sort(), system: input.system,
        text: input.messages.map((m: any) => m.content.map((b: any) => b.text ?? '').join('')),
        routed: agent.session.requestHeader().config, sameSignal: signal === control.signal })
      if (spec.action === 'outside') session.append('user/message', createUserMessage({ content: [{ type: 'text', text: 'outside span' }], source: { kind: 'user' } }), { surfaceOp: 'append' })
      if (spec.action === 'hook-error') throw new ManualCompactionError('busy', 'hook failed')
      return { summary: [{ type: 'text', text: 'custom checkpoint' }], provider: 'custom', model: 'template',
        rawOutput: [{ type: 'text', text: 'raw' }], llmStreamCall: spec.marker,
        compactionId: 'spoofed', sourceCommandId: 'spoofed', extra: 'private data',
        ...spec.mode === 'transaction-private-fields' ? { shadowedTokenCount: -1 } : {} }
    }
    let outcome: any
    try {
      const result = await compactSurfaceRegion({ meter: ctx.tokenMeter, summarize }, session, 0, 0,
        { session } as any, { owner: manual ? null : 'current-turn', stability: manual ? 'selected-span' : 'whole-surface',
          sourceCommandId: 'real-command', ...spec.flush === undefined ? {} : { flush: async () => {
            flushes++
            if (spec.flush === 'cancel') control.abort(reason)
            if (spec.flush !== 'void') throw new Error('flush failed')
          } } }, control.signal)
      outcome = { shadowedSeqs: result.shadowedSeqs, shadowedTokenCount: result.shadowedTokenCount }
    } catch (error: any) { outcome = { error: true, code: error.code ?? null, callerReason: error === reason } }
    const opening = session.events.find(e => e.type === 'compaction/start')!
    const summaries = session.events.filter(e => e.type === 'compaction/summary').map(e => {
      const { compactionId, ...body } = e.data
      return { ...body, sameIdentity: compactionId === opening.data.compactionId }
    })
    return { mode: spec.mode, inputs, outcome, summaries, flushes, generation: session.surface.replaceGeneration,
      nodes: session.surface.nodes, events: session.events.filter(e => e.type.startsWith('compaction/')).map(e => ({ type: e.type, error: 'error' in e.data })) }
  } finally { await ctx.fiber.dispose() }
}

class Adapter extends LlmAdapter {
  requests: any[] = []
  resolutions: any[] = []
  constructor(public window: number | null, private spec: any) { super() }
  async resolveModel(provider: string, model: string): Promise<any> {
    this.resolutions.push({ provider, model })
    return { provider, id: model, name: model, ...this.window === null ? {} : { context: { contextWindow: this.window } } }
  }
  async * stream(request: any): AsyncGenerator<any> {
    this.requests.push({ provider: request.provider, model: request.model, maxTokens: request.maxTokens,
      system: request.system ?? null, tools: request.tools ?? null,
      text: request.messages.map((m: any) => m.content.map((b: any) => b.text ?? '').join('')).join('\n') })
    const text = this.spec.decreasingSummary && this.requests.length === 1 ? 'long first checkpoint '.repeat(5) : 'small checkpoint'
    yield { type: 'text-delta', index: 0, text }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}

it('observes pinned compaction policies and real routed transactions', async () => {
  const cases = JSON.parse(await readFile('scripts/oracles/compaction-cases.json', 'utf8'))
  const rows: any[] = []
  for (const spec of cases) {
    if (spec.kind === 'transaction') {
      rows.push(await transaction(spec))
      continue
    }
    if (spec.kind === 'config') {
      try {
        const config = resolveConfig(spec.config)
        if (spec.target === undefined) {
          rows.push({ mode: spec.mode, config, frozen: Object.isFrozen(config) })
          continue
        }
        const policy = resolveTargetPolicy(config, spec.target)
        const compact = resolveCompactSpec(policy, spec.window)
        rows.push({ mode: spec.mode, config, policy, compact,
          frozen: Object.isFrozen(config) && Object.isFrozen(config.modelPolicies) && Object.isFrozen(compact.target) })
      } catch (error: any) {
        rows.push({ mode: spec.mode, error: true, targetKey: error.targetKey ?? null, message: error.message })
      }
      continue
    }
    const ctx = new Context()
    try {
      await ctx.plugin(SessionStore)
      await ctx.plugin(LlmRuntime)
      await ctx.plugin(TokenMeter)
      const adapter = new Adapter(spec.window === undefined || spec.window === 'measured' ? 1000 : spec.window, spec)
      ctx.llm.registerAdapter(['routed', 'summary-p'], adapter)
      const session = ctx.sessions.create()
      for (let turn = 1; turn <= 4; turn++) {
        const text = 'fixture '.repeat(40)
        session.append('turn/start', { turn })
        session.append('user/message', createUserMessage({ content: [{ type: 'text', text: text + ' user ' + turn }], source: { kind: 'user' } }), { surfaceOp: 'append' })
        session.append('step/start', { turn, step: 1 })
        if (turn === 1 && !spec.headerless) session.append('request/header', { header: {
          config: { provider: 'routed', model: 'shared' }, ...spec.systemChars === undefined ? {} : { system: 'x'.repeat(spec.systemChars) },
        }, reason: 'initial' })
        session.append('assistant/message', { turn, step: 1, message: createMessage({ role: 'assistant',
          content: [{ type: 'text', text: text + ' assistant ' + turn }], source: { provider: 'routed', model: 'shared' } }) }, { surfaceOp: 'append' })
        session.append('step/end', { turn, step: 1 })
        session.append('turn/end', { turn, reason: { kind: 'completed' } })
      }
      session.append('turn/start', { turn: 5 })
      if (spec.window === 'measured') adapter.window = ctx.tokenMeter.measure(session).totalTokens
      const engine = new BasicCompactionEngine(ctx, spec.config)
      const agent: any = { session, options: { provider: 'fallback', model: 'fallback' } }
      const control = new AbortController()
      if (spec.aborted) control.abort('stop')
      const outcomes: any[] = []
      for (const action of spec.actions ?? [spec.trigger ?? 'pressure']) {
        try {
          const result = action === 'overflow'
            ? await ctx.waterfall('agent/request-error', { agent, failure: { code: 'CONTEXT_WINDOW_EXCEEDED', message: 'overflow' }, signal: control.signal } as any, () => 'delegate' as any)
            : action === 'pre-step' ? await ctx.waterfall('agent/pre-step', { agent, signal: control.signal } as any, () => 'delegate' as any)
            : await engine.compactIfNeeded(agent, action, control.signal)
          outcomes.push(result === null || result === undefined ? null : result === 'delegate' ? result
            : result.kind === 'retry' ? result : { shadowedRange: result.shadowedRange, shadowedSeqs: result.shadowedSeqs, shadowedTokenCount: result.shadowedTokenCount })
        } catch (error: any) { outcomes.push({ error: true, targetKey: error.targetKey ?? null }) }
      }
      rows.push({ mode: spec.mode, outcomes, requests: adapter.requests, resolutions: adapter.resolutions,
        generation: session.surface.replaceGeneration, measurement: ctx.tokenMeter.measure(session),
        compactionEvents: session.events.filter(e => e.type.startsWith('compaction/')).map(e => ({ type: e.type, seq: e.seq })) })
    } finally { await ctx.fiber.dispose() }
  }
  expect(rows).toHaveLength(cases.length)
  await writeFile(process.env.COMPACTION_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
})
