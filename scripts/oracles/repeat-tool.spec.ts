import { it, expect } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { SessionId } from '@deepseek-ai/dsh-session'
import { defineContentToolFixture } from '@deepseek-ai/dsh-tools'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import * as Guard from '@deepseek-ai/dsh-repeat-tool-reminder'
import { MockAdapter, textResponse, toolCallResponse } from '../../reference/packages/core/agent-loop/tests/mock-adapter.ts'

function noticeTexts(messages: any[]) {
  return messages.flatMap(message => typeof message.content === 'string' ? [message.content]
    : message.content?.filter((block: any) => block.type === 'text').map((block: any) => block.text) ?? [])
    .filter((text: string) => text.startsWith('You are repeating the exact same tool call') || text.startsWith('Repeated tool call detected:'))
}

it('observes real source AgentLoop guard notices and downstream results', async () => {
  const cases = JSON.parse(await readFile('scripts/oracles/repeat-tool-cases.json', 'utf8'))
  const rows: unknown[] = []
  for (const spec of cases) {
    const ctx = new Context()
    try {
      await mountAgentLoopTestDependencies(ctx)
      await ctx.plugin(AgentLoop, { agents: [] })
      await ctx.plugin(Guard, spec.config)
      const received: string[] = []
      for (const name of ['probe', 'other']) ctx.tools.register(defineContentToolFixture({
        name, description: 'fixture', parameters: {}, async execute(args) {
          received.push(JSON.stringify(args))
          return [{ type: 'text', text: 'ok' }]
        },
      }))
      if (spec.policy === 'deny') ctx.on('tools/pre-execute', () => ({ kind: 'deny', reason: 'sealed' }))
      if (spec.policy === 'block') ctx.on('tools/post-execute', () => ({ kind: 'block', feedback: [{ type: 'text', text: 'blocked' }] }))
      if (spec.policy === 'replace') ctx.on('tools/post-execute', () => ({ kind: 'accept', value: [{ type: 'text', text: 'replaced' }] }))
      let callId = 0
      const adapter = new MockAdapter(spec.turns.flatMap((turn: string[][]) => [
        ...turn.map(([name, args]) => toolCallResponse(`call-${++callId}`, name!, JSON.parse(args!))), textResponse('done'),
      ]))
      ctx.llm.registerAdapter(['fixture'], adapter)
      const agent = ctx.agentLoop.create(SessionId(spec.mode), { provider: 'fixture', model: 'fixture' })
      for (const _turn of spec.turns) {
        agent.followup(createUserMessage({ content: [{ type: 'text', text: 'go' }], source: { kind: 'user' } }))
        await agent.whenIdle()
      }
      const events = [...agent.session.events]
      if (spec.mode === 'proto-key-loss') expect(received).toEqual(spec.turns[0].map((call: string[]) => call[1]))
      rows.push({ mode: spec.mode,
        notices: events.filter(event => event.type === 'user/message' && (event.data as any).source?.plugin === 'repeat-tool-reminder')
          .map(event => ({ content: (event.data as any).content, source: (event.data as any).source })),
        requests: adapter.requests.map(request => noticeTexts(request.messages as any[])),
        results: events.filter(event => event.type === 'tool/result').map(event => {
          const block = (event.data as any).message.content[0]
          return { isError: block.isError ?? false, content: block.content }
        }),
      })
    } finally { await ctx.fiber.dispose() }
  }
  await writeFile(process.env.REPEAT_TOOL_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
})
