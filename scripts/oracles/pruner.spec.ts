import { expect, it } from 'vitest'
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { Context } from '@deepseek-ai/cordis'
import Loader from '@deepseek-ai/cordis-plugin-loader'
import Include from '@deepseek-ai/cordis-plugin-include'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import * as SessionInvariant from '@deepseek-ai/dsh-session/invariant'
import InvariantRegistry from '@deepseek-ai/dsh-invariants'
import TokenMeter from '@deepseek-ai/dsh-token-meter'
import ToolResultPruner, { DEFAULTS, PRUNE_MARKER, codePointLength, resolveConfig } from '@deepseek-ai/dsh-compaction-tool-result-pruner'

const SMALL = { thresholdChars: 50, headChars: 4, tailChars: 3 }
function blocks(recipe: string): any[] {
  const text = (value: string, extra = {}) => ({ type: 'text', text: value, ...extra })
  if (recipe === 'short') return [text('a😀b'), { type: 'reasoning', text: 'unmeasured' }]
  if (recipe === 'threshold') return [text('x'.repeat(50))]
  if (['astral', 'pairs', 'isolated', 'combining'].includes(recipe)) {
    return [text(({ astral: '😀', pairs: '\ud83d\ude00', isolated: '\ud83dX\ude00', combining: 'e\u0301' } as any)[recipe].repeat(60), { extra: { retain: true } })]
  }
  if (recipe === 'nontext') return [{ type: 'reasoning', text: 'x'.repeat(200) }, { type: 'image', data: 'rich' }]
  if (recipe === 'empty') return [text(''), text('A'.repeat(4)), text(''), text('B'.repeat(60)), text(''), text('C'.repeat(3)), text('')]
  if (recipe === 'zero') return [text('x'.repeat(100))]
  if (recipe === 'rich') return [text('A'.repeat(40), { label: 'first' }), { type: 'reasoning', text: 'private-rich' }, text('B'.repeat(30)),
    { type: 'tool-call', id: 'nested', name: 'nested', arguments: '{}' }, text('C'.repeat(30), { label: 'last' })]
  throw new Error(recipe)
}

function appendStep(session: Session, turn: number, call: string, content: any[], extra = {}) {
  session.append('turn/start', { turn })
  session.append('step/start', { turn, step: 1 })
  const assistant = { id: 'assistant-' + call, role: 'assistant', source: { kind: 'model', provider: 'test', model: 'model' },
    content: [{ type: 'tool-call', id: call, name: 'bash', arguments: '{}' }] }
  session.append('assistant/message', { turn, step: 1, message: assistant } as any, { surfaceOp: 'append' })
  session.append('tool/call', { turn, step: 1, callId: call, name: 'bash', arguments: '{}' } as any)
  const message = { id: 'result-' + call, role: 'user', source: { kind: 'tool', callId: call },
    content: [{ type: 'tool-result', toolCallId: call, isError: true, content, futureBlock: { keep: true } }], futureMessage: { keep: true } }
  const event = session.append('tool/result', { turn, step: 1, message, ...extra } as any, { surfaceOp: 'append' })
  session.append('step/end', { turn, step: 1 })
  session.append('turn/end', { turn, reason: { kind: 'completed' } })
  return event.seq
}

async function loaderObservation(ctx: Context, spec: any): Promise<any> {
  if (spec.recipe === 'stale') {
    await ctx.plugin(TokenMeter)
    try {
      await ctx.plugin(ToolResultPruner, (spec.config ?? { maxChars: 100 }) as never)
      return { mode: spec.mode, error: null }
    } catch (error) { return { mode: spec.mode, error: (error as Error).message } }
  }
  if (spec.recipe === 'lifecycle') {
    const fiber = await ctx.plugin(ToolResultPruner, SMALL)
    const pending = ctx.get('toolResultPruner') === undefined
    const meter = await ctx.plugin(TokenMeter)
    const first = ctx.get('toolResultPruner')
    await meter.dispose()
    const retired = ctx.get('toolResultPruner') === undefined
    await ctx.plugin(TokenMeter)
    const current = ctx.get('toolResultPruner')!
    const reload = current !== undefined && current !== first
    const config = current.config
    await fiber.dispose()
    return { mode: spec.mode, pending, retired, reload, config, unloaded: ctx.get('toolResultPruner') === undefined }
  }
  const root = await mkdtemp(join(tmpdir(), 'pruner-loader-'))
  try {
    const path = join(root, 'cordis.yml')
    await writeFile(path, "- name: '@deepseek-ai/dsh-token-meter'\n"
      + "- name: '@deepseek-ai/dsh-compaction-tool-result-pruner'\n"
      + '  config:\n    thresholdChars: 100\n    headChars: 20\n    tailChars: 10\n')
    ctx.baseUrl = pathToFileURL(root).href + '/'
    await ctx.plugin(Loader)
    ctx.loader.builtins.include = Include
    ctx.loader.internal = { version: 'v2', async import(specifier: string) {
      if (specifier === '@deepseek-ai/dsh-token-meter') return TokenMeter
      if (specifier === '@deepseek-ai/dsh-compaction-tool-result-pruner') return ToolResultPruner
      throw new Error('unexpected import: ' + specifier)
    } } as any
    await ctx.loader.create({ name: 'cordis:include', config: { path: pathToFileURL(path).href } })
    await ctx.loader.await()
    const service = ctx.get('toolResultPruner')!
    const config = service.config, loaded = service instanceof ToolResultPruner
    await ctx.loader.root.update([])
    const schema = ToolResultPruner.Config
    const metadata = { type: schema.type, meta: schema.meta,
      fields: Object.entries(schema.dict!).map(([key, value]) => ({ key, type: value.type, meta: value.meta })) }
    return { mode: spec.mode, config, loaded, unloaded: ctx.get('toolResultPruner') === undefined, schema: metadata }
  } finally { await ctx.fiber.dispose(); await rm(root, { recursive: true, force: true }) }
}

async function observe(spec: any): Promise<any> {
  const ctx = new Context()
  try {
    if (spec.kind === 'loader') return await loaderObservation(ctx, spec)
    if (spec.kind === 'config') {
      const raw = { ...spec.config }
      try {
        const config = resolveConfig(raw)
        raw.headChars = 1
        return { mode: spec.mode, config, frozen: Object.isFrozen(config), defaults: DEFAULTS, defaultsFrozen: Object.isFrozen(DEFAULTS),
          negativeZero: Object.entries(config).filter(([, value]) => Object.is(value, -0)).map(([key]) => key) }
      } catch (error) { return { mode: spec.mode, error: (error as Error).message } }
    }
    if (spec.recipe === 'invariants') {
      await ctx.plugin(SessionStore)
      await ctx.plugin(InvariantRegistry)
      await ctx.plugin(SessionInvariant)
    }
    const meter = new TokenMeter(ctx)
    const config = spec.config ?? (spec.recipe === 'zero' ? { thresholdChars: codePointLength(PRUNE_MARKER), headChars: 0, tailChars: 0 } : SMALL)
    const pruner = new ToolResultPruner(ctx, config)
    if (spec.kind === 'content') {
      const original = blocks(spec.recipe)
      const result = pruner.pruneContent(original)
      return { mode: spec.mode, before: pruner.measureContent(original), result,
        after: result === null ? null : pruner.measureContent(result),
        richIdentity: result === null || original.filter(b => b.type !== 'text').every(b => result.includes(b)), original }
    }
    const session = spec.recipe === 'invariants' ? ctx.sessions.create(SessionId('probe')) : Session.create(SessionId('probe'))
    const first = appendStep(session, 1, 'a', spec.recipe === 'preserve' ? blocks('rich') : [{ type: 'text', text: 'A'.repeat(100) }],
      { isError: true, error: { name: 'ExitError', code: 'EXIT_1' }, meta: { diff: ['a', 'b'] }, futureField: { nested: true } })
    let second: number | null = null
    if (!['preserve', 'invariants'].includes(spec.recipe)) {
      appendStep(session, 2, 'b', [{ type: 'text', text: 'short' }])
      second = appendStep(session, 3, 'c', [{ type: 'text', text: 'C'.repeat(80) }])
    }
    let rejection = null
    if (spec.recipe === 'invariants') {
      const beforeTokens = meter.measure(session).totalTokens
      try { pruner.pruneSession(session) } catch (error) {
        rejection = { error: (error as Error).message, addedEvents: session.events.length - 7,
          beforeTokens, afterTokens: meter.measure(session).totalTokens, generation: session.surface.replaceGeneration }
      }
    }
    session.append('turn/start', { turn: second === null ? 2 : 4 })
    const originalAppend = session.append.bind(session)
    let replacements = 0
    session.append = ((type: any, data: any, options: any = {}) => {
      if (type === 'tool/result' && options.surfaceOp?.op === 'replace') {
        replacements++
        if (replacements === 2 && spec.recipe === 'partial') throw new Error('second replacement rejected')
      }
      const event = originalAppend(type, data, options)
      if (type === 'compaction/prune' && replacements === 0 && spec.recipe === 'snapshot') {
        originalAppend('tool/result', { ...session.events[second!]!.data } as any, { surfaceOp: 'append' })
      }
      return event
    }) as typeof session.append
    let error = null, result = null
    try { result = pruner.pruneSession(session) } catch (caught) { error = (caught as Error).message }
    session.append = originalAppend
    const repeat = ['preserve', 'multiple', 'invariants'].includes(spec.recipe) ? pruner.pruneSession(session) : null
    const replay = Session.create(session.id, [...session.events])
    const events = session.events.map(({ time, ...event }) => event)
    return { mode: spec.mode, result, error, repeat, rejection, events, nodes: [...session.surface.nodes], generation: session.surface.replaceGeneration,
      messages: session.deriveMessages(), replayMessages: replay.deriveMessages(), replayGeneration: replay.surface.replaceGeneration,
      originalPrice: meter.estimateMessage((session.events[first]!.data as any).message) }
  } finally { await ctx.fiber.dispose() }
}

it('observes pinned source configuration, Unicode, rich blocks and durable pruning', async () => {
  const specs = JSON.parse(await readFile('scripts/oracles/pruner-cases.json', 'utf8'))
  const rows = []
  for (const spec of specs) rows.push(await observe(spec))
  expect(rows).toHaveLength(specs.length)
  await writeFile(process.env.PRUNER_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
})
