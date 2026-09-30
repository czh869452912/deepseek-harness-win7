import { it, expect } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import { createUserMessage, createMessage, LlmRuntime, LlmAdapter } from '@deepseek-ai/dsh-llm'
import SessionStore from '@deepseek-ai/dsh-session'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import TokenMeter from '@deepseek-ai/dsh-token-meter'
import { estimateContent, estimateHeader } from '../../reference/packages/llm/token-meter/src/estimate.ts'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { SessionId } from '@deepseek-ai/dsh-session'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import { MockAdapter, textResponse } from '../../reference/packages/core/agent-loop/tests/mock-adapter.ts'

class Adapter extends LlmAdapter {
  imageRequestPricing(_provider: string, model: string): any {
    return model === 'vision' ? { priceImages: (refs: any[]) => refs.map((ref, index) => ({ visualTokens: ref.width + index, text: 'Image handle' })) } : undefined
  }
  async * stream(): AsyncGenerator<any> { throw new Error('pricing fixture does not generate') }
}

it('observes pinned token measurements, projection states and schema prices', async () => {
  const cases = JSON.parse(await readFile('scripts/oracles/token-meter-cases.json', 'utf8'))
  const rows: any[] = []
  for (const spec of cases) {
    const ctx = new Context()
    try {
      await ctx.plugin(SessionStore)
      await ctx.plugin(SessionProjectionRegistry)
      await ctx.plugin(LlmRuntime)
      ctx.llm.registerAdapter(['mock'], new Adapter())
      await ctx.plugin(TokenMeter)
      const session = ctx.sessions.create()
      const output: any[] = []
      const user = (text: any, options: any = { surfaceOp: 'append' }) => session.append('user/message',
        createUserMessage({ content: typeof text === 'string' ? [{ type: 'text', text }] : text, source: { kind: 'user' } }), options)
      let step = 0
      for (const action of spec.actions) {
        const header = action.header === undefined ? { config: { provider: 'mock', model: 'mock' }, system: 'system' } : action.header
        switch (action.op) {
          case 'user': user(action.text); break
          case 'header': session.append('request/header', { header, reason: 'initial' }); break
          case 'call':
          case 'input-call': {
            step += 1
            session.append('step/start', { turn: 1, step })
            if (action.op === 'input-call') user(action.input)
            if (header !== null) session.append('request/header', { header, reason: 'initial' })
            const text = action.text ?? 'answer'
            const sourceEventSeqs: number[] = []
            if (action.provenance === 'exact') {
              const providerText = action.providerText ?? text
              const chunks = [{ type: 'block-start', index: 0, blockType: 'text' },
                { type: 'text-delta', index: 0, text: providerText },
                { type: 'block-end', index: 0, block: { type: 'text', text: providerText } },
                { type: 'finish', reason: { kind: 'stop' } }]
              for (const chunk of chunks) sourceEventSeqs.push(session.append('assistant/chunk', { turn: 1, step, chunk } as any).seq)
            }
            session.append('assistant/message', { turn: 1, step,
              message: createMessage({ role: 'assistant', content: text === '' ? [] : [{ type: 'text', text }], source: { kind: 'model', provider: 'mock', model: 'mock' } }),
              ...action.usage === undefined ? {} : { usage: action.usage },
            }, { surfaceOp: 'append', ...action.provenance === undefined ? {} : { sourceEventSeqs } })
            session.append('step/end', { turn: 1, step })
            break
          }
          case 'replace': {
            const nodes = ctx.tokenMeter.measure(session).nodes
            const selected = nodes.slice(nodes.findIndex(row => row.seq === action.start), nodes.findIndex(row => row.seq === action.end) + 1)
            if (action.metered) session.append('compaction/prune', { shadowedRange: { start: action.start, end: action.end }, shadowedSeqs: selected.map(row => row.seq), shadowedTokenCount: selected.reduce((total, row) => total + row.heuristicTokens, 0) })
            user(action.text, { surfaceOp: { op: 'replace', start: action.start, end: action.end }, sourceEventSeqs: selected.map(row => row.seq) })
            break
          }
          case 'usage': session.append('assistant/chunk', { turn: 1, step: 1, chunk: { type: 'usage', usage: action.usage } }); break
          case 'retry': session.append('llm/retry-started', { turn: 1, step: 1 } as any); break
          case 'context': session.append('request/context', { ...action.contextWindow === undefined ? {} : { contextWindow: action.contextWindow } }); break
          case 'estimate': output.push({ content: estimateContent(action.content), header: estimateHeader(action.header) }); break
          case 'measure': output.push({ measurement: ctx.tokenMeter.measure(session, action.header), projection: ctx.sessionProjections.snapshot(session), checkpoint: ctx.sessionProjections.checkpoint(session) }); break
          default: throw new Error('unknown action')
        }
      }
      rows.push({ mode: spec.mode, output })
    } finally { await ctx.fiber.dispose() }
  }
  await writeFile(process.env.TOKEN_METER_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
})

it('reproduces provider input double counting in actual pinned AgentLoop', async () => {
  const ctx = new Context()
  try {
    await mountAgentLoopTestDependencies(ctx)
    if (ctx.get('sessionProjections') === undefined) await ctx.plugin(SessionProjectionRegistry)
    await ctx.plugin(AgentLoop, { agents: [] })
    await ctx.plugin(TokenMeter)
    const response = () => textResponse('answer').map(chunk => chunk.type === 'usage'
      ? { type: 'usage' as const, usage: { inputTokens: 1000, outputTokens: 20, totalTokens: 1020 } } : chunk)
    const adapter = new MockAdapter([response(), response()])
    ctx.llm.registerAdapter(['fixture'], adapter)
    const agent = ctx.agentLoop.create(SessionId('meter-loop'), { provider: 'fixture', model: 'fixture' })
    const results: any[] = []
    for (const text of ['first', 'second']) {
      agent.followup(createUserMessage({ content: [{ type: 'text', text }], source: { kind: 'user' } }))
      await agent.whenIdle()
      const result = ctx.tokenMeter.measure(agent.session)
      expect(result.baseline).toMatchObject({ kind: 'usage', tokens: 1020 })
      expect(result.surfaceDeltaTokens).toBe(10)
      expect(result.totalTokens).toBe(1030)
      expect(adapter.requests.at(-1)!.messages.some(message => message.content.some(block => block.type === 'text' && block.text === text))).toBe(true)
      results.push(result)
    }
    await writeFile(process.env.TOKEN_METER_OUTPUT! + '.loop.json', JSON.stringify(results, null, 2) + '\n')
  } finally { await ctx.fiber.dispose() }
})
