import { describe, expect, it } from 'vitest'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { SessionId } from '@deepseek-ai/dsh-session'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import InvariantRegistry from '@deepseek-ai/dsh-invariants'
import * as SessionInvariant from '@deepseek-ai/dsh-session/invariant'
import * as AgentInvariant from '@deepseek-ai/dsh-agent/invariant'
import * as AgentLoopInvariant from '@deepseek-ai/dsh-agent-loop/invariant'
import { MockAdapter, textResponse, toolCallResponse } from '../../reference/packages/core/agent-loop/tests/mock-adapter.ts'

const sourceCommit = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'

describe('actual Source agent runtime context', () => {
  it('preserves complete attributed model and durable messages at every proposed step', async () => {
    expect(process.version).toBe('v22.22.2')
    expect(execFileSync('git', ['-C', 'reference', 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()).toBe(sourceCommit)
    expect(execFileSync('git', ['-C', 'reference', 'status', '--porcelain'], { encoding: 'utf8' }).trim()).toBe('')
    const observations = []
    for (const action of ['change', 'clear', 'same', 'empty']) for (const configuration of ['base', 'max-tokens', 'reasoning', 'both']) {
      const ctx = new Context()
      const reasoning: any = configuration === 'reasoning' || configuration === 'both' ? {efforts:[{id:'high',name:'High'}],defaultEffort:'high'} : undefined
      const adapter = new MockAdapter([toolCallResponse('advance-call', 'advance', {}), textResponse('finished')], reasoning)
      const captured: any[] = []
      const signals: AbortSignal[] = []
      const originalStream = adapter.stream.bind(adapter)
      adapter.stream = async function* (options) {
        const signal = options.signal
        signals.push(signal!)
        captured.push({...structuredClone({...options, signal: undefined}), signal: {
          present: signal instanceof AbortSignal,
          aborted: signal?.aborted,
          sameAsFirst: signal === signals[0],
        }})
        yield* originalStream(options)
      }
      await mountAgentLoopTestDependencies(ctx)
      await ctx.plugin(InvariantRegistry)
      await ctx.plugin(SessionInvariant)
      await ctx.plugin(AgentInvariant)
      await ctx.plugin(AgentLoopInvariant)
      await ctx.plugin(AgentLoop, { agents: [] })
      ctx.llm.registerAdapter(['mock'], adapter)
      let current = action === 'empty' ? '' : 'initial {{value}}'
      ctx.systemPrompt.variable('value', () => 'interpolated')
      ctx.systemPrompt.context({ name: 'policy', order: 10, text: () => current })
      ctx.tools.register({
        name: 'advance', description: 'Change dynamic context',
        parameters: { type: 'object', properties: {}, additionalProperties: false },
        output: {
          schema: { type: 'object', properties: { changed: { type: 'boolean' } }, required: ['changed'], additionalProperties: false },
          render: () => [{ type: 'text', text: 'changed' }],
        },
        execute: async () => {
          current = action === 'change' ? 'changed {{value}}' : action === 'clear' ? '' : current
          return { changed: true }
        },
      })
      const parent = ctx.agentLoop.create(SessionId('parent'), { provider: 'mock', model: 'mock',
        ...(configuration === 'max-tokens' || configuration === 'both' ? {maxTokens:17} : {}),
        ...(reasoning ? {reasoningEffort:'high' as any} : {}),
      })
      try {
        parent.followup(createUserMessage({ content: [{ type: 'text', text: 'advance context' }], source: { kind: 'user' } }))
        await parent.whenIdle()
        const snapshots = parent.session.events.filter(event => event.type === 'user/message'
          && event.data.source?.kind === 'plugin' && event.data.source.plugin === '@deepseek-ai/dsh-system-prompt')
          .map(event => event.data)
        expect(adapter.requests).toHaveLength(2)
        expect(snapshots).toHaveLength(action === 'empty' ? 0 : action === 'same' ? 1 : 2)
        observations.push({ name: action + '/' + configuration, requests: captured, snapshots })
      } finally {
        await ctx.fiber.dispose()
      }
    }
    const output = resolve(process.env.DSH_RUNTIME_FULL_REQUEST_OUTPUT!)
    expect(existsSync(output)).toBe(false)
    const inputs = {}
    const files = ['reference/packages/core/agent-loop/src/agent.ts', 'reference/packages/core/agent-loop/src/runtime-context.ts',
      'reference/packages/core/system-prompt/src/index.ts', 'reference/packages/core/agent-loop/tests/mock-adapter.ts',
      'scripts/oracles/runtime_full_request.probe.spec.ts', 'scripts/oracles/vitest.runtime-full-request-probe.config.mts',
      'reference/packages/llm/llm/src/index.ts', 'reference/packages/llm/llm/src/types.ts',
      'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts', 'migration/modules.json']
    for (const path of files) inputs[path] = createHash('sha256').update(readFileSync(path)).digest('hex')
    writeFileSync(output, JSON.stringify({ sourceCommit, node: process.version, inputs, observations }, null, 2) + '\n', { encoding: 'utf8', flag: 'wx' })
  })
})
