import { it } from './official/node_modules/vitest/dist/index.js'
import { writeFileSync } from 'node:fs'
import { AcpModelControl } from '../../reference/packages/acp/acp/src/model-control.ts'
import { assistantUpdates, toolCallUpdate, toolResultUpdate } from '../../reference/packages/acp/acp/src/updates.ts'

class ModelRuntime {
  default: string | undefined
  available = true
  catalogAvailable = true
  calls: unknown[] = []
  gate: Promise<void> | undefined
  entered: (() => void) | undefined
  constructor(defaultEffort: string | undefined = 'high') { this.default = defaultEffort }
  listProviders() { return [{ id: 'mock', name: 'Mock' }, { id: 'other', name: 'Other' }] }
  async listModels(provider: string) {
    if (!this.catalogAvailable) throw new Error('catalog missing')
    return [{ provider, id: 'first', name: 'First' }, { provider, id: 'next', name: 'Next', description: 'A different route' }]
  }
  async resolveModelInfo(provider: string, model: string) {
    if (!this.available) throw new Error('route missing')
    return { provider, id: model, name: model, inputModalities: ['text', 'image'], reasoning: {
      efforts: [{ id: 'low', name: 'Low', description: 'Less thought.' }, { id: 'high', name: 'High' }],
      ...(this.default === undefined ? {} : { defaultEffort: this.default }),
    } }
  }
  async resolveCallConfig(selection: Record<string, unknown>) {
    this.calls.push({ ...selection })
    this.entered?.()
    if (this.gate !== undefined) await this.gate
    if (!this.available) throw new Error('route missing')
    return { ...selection, ...(selection.reasoningEffort === undefined && this.default !== undefined ? { reasoningEffort: this.default } : {}) }
  }
}

it('observes complete selected model/control and committed update fields', async () => {
  const observations: unknown[] = []
  let runtime = new ModelRuntime()
  let control = new AcpModelControl(runtime as any, undefined)
  const errors = []
  for (const value of [false, 'missing']) {
    try { await control.set('model', value) } catch (error) { errors.push((error as Error).message) }
  }
  observations.push({ mode: 'absent', options: await control.options(), snapshot: control.snapshot() ?? null, errors, calls: [...runtime.calls] })
  control = new AcpModelControl(runtime as any, { provider: 'mock', model: 'first' })
  observations.push({ mode: 'catalog', initial: await control.options(), changed: await control.set('model', '["other","next"]'), snapshot: control.snapshot() })
  runtime = new ModelRuntime()
  runtime.catalogAvailable = false
  control = new AcpModelControl(runtime as any, { provider: 'private', model: '模型"' })
  observations.push({ mode: 'unlisted', options: await control.options(), snapshot: control.snapshot() })
  const defaults = []
  for (const providerDefault of [true, false]) {
    runtime = new ModelRuntime()
    if (providerDefault) runtime.default = undefined
    control = new AcpModelControl(runtime as any, { provider: 'mock', model: 'first' })
    const initial = await control.options()
    let rejected = ''
    try { await control.set('reasoning_effort', 'extreme') } catch (error) { rejected = (error as Error).message }
    const changed = await control.set('reasoning_effort', 'low')
    const reset = await control.set('reasoning_effort', providerDefault ? '' : 'high')
    defaults.push({ providerDefault, initial, rejected, changed, reset, snapshot: control.snapshot() })
  }
  observations.push({ mode: 'defaults', defaults })
  runtime = new ModelRuntime()
  control = new AcpModelControl(runtime as any, { provider: 'mock', model: 'first' })
  const initial = await control.options()
  runtime.available = false
  runtime.catalogAvailable = false
  const unavailable = await control.options()
  runtime.available = true
  runtime.catalogAvailable = true
  observations.push({ mode: 'outage', initial, unavailable, restored: await control.options(), snapshot: control.snapshot() })
  runtime = new ModelRuntime()
  const entered = Promise.withResolvers<void>()
  const release = Promise.withResolvers<void>()
  runtime.gate = release.promise
  runtime.entered = () => entered.resolve()
  control = new AcpModelControl(runtime as any, { provider: 'mock', model: 'first' })
  const pending = control.set('model', 'invalid').catch(error => (error as Error).message)
  await entered.promise
  let completed = false
  const following = control.set('reasoning_effort', 'low').then(value => { completed = true; return value })
  await Promise.resolve()
  const blocked = !completed
  release.resolve()
  observations.push({ mode: 'serialized', blocked, rejected: await pending, next: await following, calls: runtime.calls, snapshot: control.snapshot() })
  runtime = new ModelRuntime()
  control = new AcpModelControl(runtime as any, { provider: 'mock', model: 'first' })
  await control.options()
  const admitted = control.snapshot()!
  control.pinTurn(3, admitted)
  admitted.model = 'external mutation'
  await control.set('model', '["other","next"]')
  const pinned = { ...control.selection.current }
  control.releaseTurn(2)
  const wrongTurn = { ...control.selection.current }
  control.releaseTurn(3)
  observations.push({ mode: 'pin', pinned, wrongTurn, released: control.selection.current, future: control.snapshot() })
  const store = { readImage: async (ref: unknown) => ({ ref, data: Buffer.from('image') }) }
  const ctx = { get: (name: string) => name === 'attachments' ? store : name === 'tokenMeter' ? { measure: () => ({ totalTokens: 7 }) } : undefined }
  const event = { type: 'assistant/message', data: { usage: {}, message: { id: 'message-1', content: [
    { type: 'reasoning', text: '' }, { type: 'reasoning', text: 'thought' }, { type: 'text', text: 'answer' },
    { type: 'image', attachment: { mediaType: 'image/png' } }, { type: 'tool-call', id: 'hidden', name: 'hidden', arguments: '{}' },
  ] } } }
  const calls = ['{', 'NaN', 'Infinity', 'null', '{"value":[1,"中文"]}'].map(argumentsValue => toolCallUpdate({ data: { callId: 'call', name: 'echo', arguments: argumentsValue } } as any))
  const result = await toolResultUpdate(ctx as any, { data: { message: { content: [{ toolCallId: 'call', isError: true,
    content: [{ type: 'reasoning', text: 'hidden' }, { type: 'text', text: 'failed' }, { type: 'image', attachment: { mediaType: 'image/png' } }] }] } } } as any)
  observations.push({ mode: 'updates', assistant: await assistantUpdates(ctx as any, { requestContext: () => ({ contextWindow: 100 }) } as any, event as any), calls, result })
  writeFileSync(process.env.ACP_MODEL_OUTPUT!, JSON.stringify(observations, null, 2))
})
