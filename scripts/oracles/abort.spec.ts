/** Actual platform + pinned Inspect observations, without an emulated JS signal. */
import { it, expect } from 'vitest'
import { writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import { CordisInspectRegistryService } from '../../reference/packages/extensions/cordis-host-runner/src/inspect-registry.ts'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import Tools, { defineContentToolFixture } from '@deepseek-ai/dsh-tools'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import * as Policy from '@deepseek-ai/dsh-tool-call-timeout-policy'

const reasons = ['omitted', 'undefined', 'null', 'false', 'zero', 'empty', 'string', 'object', 'error']
function reason(name: string): any {
  return { undefined, null: null, false: false, zero: 0, empty: '', string: 'cancelled', object: { caller: ['operator', false] }, error: new Error('fixture abort') }[name]
}
function stop(c: AbortController, name: string): void { if (name === 'omitted') c.abort(); else c.abort(reason(name)) }
function value(v: any): any { return v instanceof Error ? { name: v.name, message: v.message, ...v instanceof DOMException ? { code: v.code } : {} } : v }
function thrown(v: any): any { return { thrown: value(v) } }
async function attempt(fn: () => any): Promise<any> { try { return { value: await fn() } } catch (e) { return thrown(e) } }
const empty = { type: 'object', properties: {}, additionalProperties: false }
const manifest: any = { id: 'probe', description: 'Read', methods: [{ name: 'read', description: 'Read', inputSchema: empty, outputSchema: empty }] }

it('observes default/null cancellation and pinned Inspect consumers', async () => {
  const rows: any[] = []
  for (const name of reasons) {
    const c = new AbortController(), signal = c.signal, events: any[] = []
    const before = signal.reason === undefined
    signal.addEventListener('abort', e => events.push({ type: e.type, target: e.target === signal, reason: value(signal.reason) }), { once: true })
    stop(c, name)
    const first = signal.reason
    let same = false
    const raised = await attempt(() => { try { signal.throwIfAborted() } catch (e) { same = e === first; throw e } })
    c.abort('ignored')
    signal.addEventListener('abort', () => events.push({ late: true }))
    rows.push({ mode: `platform/${name}`, before, reason: value(signal.reason), raised, same, retained: signal.reason === first, events })
    for (const mode of ['host-before', 'host-after', 'client-before', 'client-pending']) {
      const ctx = new Context(), registry = new CordisInspectRegistryService(ctx), controller = new AbortController()
      let calls = 0
      const events: any[] = []
      ctx.on('cordis/inspect-query' as any, (request: any) => events.push({ request: request.requestId }))
      ctx.on('cordis/inspect-query-resolved' as any, (request: any) => events.push({ resolved: request.requestId }))
      registry.register({ manifest, query() { calls++; if (mode === 'host-after') stop(controller, name); return {} } })
      registry.syncClientManifest([manifest])
      if (mode.endsWith('before')) stop(controller, name)
      const pending = attempt(() => registry.query(mode.startsWith('host') ? 'host' : 'client', 'probe', 'read', undefined, { id: 'owner' } as any, controller.signal))
      if (mode === 'client-pending') { expect(events).toEqual([{ request: 'inspect-1' }]); stop(controller, name) }
      rows.push({ mode: `${mode}/${name}`, result: await pending, calls, events })
      await ctx.fiber.dispose()
    }
    {
      const ctx = new Context(), caller = new AbortController(), events: any[] = []
      let enter!: () => void
      const entered = new Promise<void>(resolve => { enter = resolve })
      let raised: any, same = false, derived = false
      try {
        await ctx.plugin(SystemPrompt); await ctx.plugin(Tools); await ctx.plugin(Policy)
        ctx.tools.register(defineContentToolFixture({ name: 'probe', description: 'read signal', parameters: {}, timeoutMs: 10000,
          async execute(_args, exec) {
            const signal = exec.signal
            derived = signal !== caller.signal
            signal.throwIfAborted()
            const ready = new Promise<void>(resolve => signal.addEventListener('abort', e => { events.push({ type: e.type, target: e.target === signal }); resolve() }, { once: true }))
            enter()
            await ready
            raised = await attempt(() => { try { signal.throwIfAborted() } catch (e) { same = e === caller.signal.reason; throw e } })
            signal.addEventListener('abort', () => events.push({ late: true }))
            return [{ type: 'text', text: 'done' }]
          },
        }))
        const pending = ctx.tools.execute({ callId: ToolCallId('probe'), name: 'probe', arguments: {}, signal: caller.signal })
        await entered; stop(caller, name)
        const result = await pending
        rows.push({ mode: `tools-fused/${name}`, derived, raised, same, events, isError: result.isError, code: result.error?.info?.code })
      } finally { await ctx.fiber.dispose() }
    }
  }
  {
    const c = new AbortController(), seen: string[] = []
    const second = () => seen.push('second')
    const first = () => { seen.push('first'); c.signal.removeEventListener('abort', second) }
    c.signal.addEventListener('abort', first)
    c.signal.addEventListener('abort', first)
    c.signal.addEventListener('abort', second)
    c.abort(null)
    rows.push({ mode: 'platform/duplicate-and-removal-during-dispatch', seen })
  }
  {
    const signal = AbortSignal.abort(null)
    rows.push({ mode: 'platform/static-abort-null', aborted: signal.aborted, result: await attempt(() => signal.throwIfAborted()) })
  }
  expect(rows).toHaveLength(56)
  await writeFile(process.env.ABORT_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
})
