import { it, vi } from 'vitest'
import { writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import Tools, { defineContentToolFixture } from '@deepseek-ai/dsh-tools'
import { ToolCallId, HarnessError } from '@deepseek-ai/dsh-llm'
import * as Policy from '@deepseek-ai/dsh-tool-call-timeout-policy'
import { deadline, idleWatchdog, TimeoutReason, timeoutOf } from '@deepseek-ai/dsh-timeout'

const modes = ['unbudgeted', 'budgeted', 'deadline-return', 'deadline-throw',
  'user-first', 'deadline-first', 'foreign-first']

it('records actual pinned tool-policy and shared-timeout observations', async () => {
  const rows: unknown[] = []
  vi.useFakeTimers()
  try {
    for (const mode of modes) {
      const ctx = new Context()
      const caller = new AbortController()
      const entered = Promise.withResolvers<void>()
      const sawAbort = Promise.withResolvers<void>()
      const release = Promise.withResolvers<void>()
      let seen: AbortSignal | undefined, postCaller = false, finished = false
      try {
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(Tools)
        await ctx.plugin(Policy)
        ctx.tools.register(defineContentToolFixture({
          name: 'probe', description: 'paired fixture', parameters: {},
          ...mode === 'unbudgeted' ? {} : { timeoutMs: 100 },
          async execute(_args, exec) {
            seen = exec.signal
            entered.resolve()
            if (mode === 'unbudgeted' || mode === 'budgeted') return [{ type: 'text', text: 'ok' }]
            if (!exec.signal.aborted) {
              await new Promise<void>(resolve => exec.signal.addEventListener('abort', () => resolve(), { once: true }))
            }
            sawAbort.resolve()
            await release.promise
            if (mode === 'deadline-throw') throw new HarnessError('web fetch aborted', 'WEB_ABORTED')
            return [{ type: 'text', text: 'released' }]
          },
        }))
        ctx.on('tools/post-execute', (exec, _result, next) => { postCaller = exec.signal === caller.signal; return next() })
        const pending = ctx.tools.execute({ callId: ToolCallId('call'), name: 'probe', arguments: {}, signal: caller.signal })
          .then(result => { finished = true; return result })
        await entered.promise
        let waitedForCleanup = false
        if (mode !== 'unbudgeted' && mode !== 'budgeted') {
          if (mode === 'user-first' || mode === 'foreign-first') {
            caller.abort(mode === 'user-first' ? 'user' : new TimeoutReason('OUTER', 30))
          }
          await vi.advanceTimersByTimeAsync(100)
          await sawAbort.promise
          waitedForCleanup = !finished
          if (mode === 'deadline-first') caller.abort('late user')
          release.resolve()
        }
        const result = await pending
        rows.push({ mode, derived: seen !== caller.signal, postCaller, waitedForCleanup,
          timeoutCode: timeoutOf(seen!)?.code ?? null,
          result: { content: result.content, isError: result.isError,
            error: result.error ? { message: result.error.message, info: result.error.info ?? null } : null },
        })
      } finally { await ctx.fiber.dispose() }
    }

    rows.push({ mode: 'number-text', messages: [100.0, 0.00001, 0.000001, 0.0000001, 1e21, 100.25, NaN, Infinity, -Infinity]
      .map(value => new TimeoutReason('TEST', value).message) })
    const outer = new AbortController()
    outer.abort(new TimeoutReason('OUTER', 30))
    using inner = deadline(outer.signal, 100, 'INNER')
    await vi.advanceTimersByTimeAsync(100)
    rows.push({ mode: 'nested', aborted: inner.signal.aborted, code: timeoutOf(inner.signal)?.code,
      local: timeoutOf(inner.signal, 'INNER') !== undefined })

    using watchdog = idleWatchdog(undefined, 100, 'IDLE')
    const stable = watchdog.signal
    const first = Promise.withResolvers<IteratorResult<number>>()
    const second = Promise.withResolvers<IteratorResult<number>>()
    watchdog.pulse()
    await vi.advanceTimersByTimeAsync(1000)
    const noDemand = !stable.aborted
    const demand = watchdog.next({ next: () => first.promise })
    await vi.advanceTimersByTimeAsync(99)
    watchdog.pulse()
    await vi.advanceTimersByTimeAsync(99)
    const pulseProtected = !stable.aborted
    first.resolve({ done: false, value: 1 })
    await demand
    await vi.advanceTimersByTimeAsync(1000)
    const idleProtected = !stable.aborted
    const late = watchdog.next({ next: () => second.promise })
    await vi.advanceTimersByTimeAsync(100)
    const blockedUntilProvider = { noDemand, pulseProtected, idleProtected, stable: watchdog.signal === stable,
      code: timeoutOf(stable)?.code }
    second.resolve({ done: true, value: undefined })
    await late
    rows.push({ mode: 'watchdog', ...blockedUntilProvider })
    await writeFile(process.env.TIMEOUT_POLICY_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
  } finally { vi.useRealTimers() }
})
