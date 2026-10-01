import { expect, it } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { Context } from '@deepseek-ai/cordis'
import { CordisInspectRegistryService } from '../../reference/packages/extensions/cordis-host-runner/src/inspect-registry.ts'
import { hostInspectProviders } from '../../reference/packages/extensions/tool-cordis/src/providers.ts'
import { SERVICE_API, EVENT_API, queryServiceApi, queryEventApi } from '../../reference/packages/extensions/tool-cordis/src/api-catalog.ts'
import { assertSupportedJsonSchema, assertObjectJsonSchema, validateJsonSchemaValue } from '@deepseek-ai/dsh-tools'

const owner: any = { id: 'owner' }, foreign: any = { id: 'foreign' }
const empty = { type: 'object', properties: {}, additionalProperties: false }
const output = { type: 'object', properties: { value: { type: 'integer' } }, required: ['value'], additionalProperties: false }
function manifest(id = 'probe'): any {
  return { id, description: 'Read-only probe', methods: [{ name: 'read', description: 'Read', inputSchema: empty, outputSchema: output }] }
}
function error(caught: any): any {
  if (typeof caught !== 'object' || caught === null) return { thrown: caught }
  return { message: caught.message, ...caught.name === 'JsonSchemaError' ? { name: caught.name, code: caught.code, violations: caught.violations } : {} }
}
async function attempt(fn: () => any): Promise<any> {
  try { const value = await fn(); return { value: value === undefined ? { undefined: true } : value } } catch (caught) { return { error: error(caught) } }
}
function recipe(spec: any, isSchema: boolean): any {
  if (!spec.recipe) return spec[isSchema ? 'schema' : 'value']
  if (spec.recipe === 'negative-zero') return isSchema ? { type: 'number', enum: [-0], const: -0 } : -0
  if (spec.recipe === 'infinite') return Infinity
  if (spec.recipe === 'utf16-pair') return '\ud83d\ude00'
  if (spec.recipe.startsWith('array-subclass')) { class Exotic extends Array {}; return new Exotic(1, spec.recipe.endsWith('child') ? 'bad' : 2) }
  if (spec.recipe === 'undefined') return isSchema ? { default: undefined } : { a: undefined }
  if (spec.recipe === 'cycle') {
    const value: any = isSchema ? { type: 'array' } : {}
    value[isSchema ? 'items' : 'self'] = value
    return value
  }
  if (spec.recipe === 'shared') { const child = { type: 'string' }; return { type: 'object', properties: { a: child, b: child } } }
  throw new Error(spec.recipe)
}
async function tick() { for (let i = 0; i < 4; i++) await Promise.resolve() }

async function registryObservation(spec: any): Promise<any> {
  const ctx = new Context(), registry = new CordisInspectRegistryService(ctx)
  const events: any[] = [], acks: any[] = []
  ctx.on('cordis/inspect-query' as any, (request: any) => { events.push({ kind: 'request', ...request }) })
  ctx.on('cordis/inspect-query-resolved' as any, (request: any) => {
    events.push({ kind: 'closed', ...request })
    acks.push(registry.resolveClientQuery(owner, request.requestId, { ok: true, data: { value: 999 } } as any))
  })
  try {
    if (spec.recipe === 'manifest') {
      const cases = [ { ...manifest(), id: '\ufeff\u2003' }, { ...manifest(), description: ' ' },
        { ...manifest(), methods: [{ ...manifest().methods[0], name: '' }] },
        { ...manifest(), methods: [manifest().methods[0], manifest().methods[0]] },
        { ...manifest(), methods: [{ ...manifest().methods[0], description: '' }] },
        { ...manifest(), methods: [{ ...manifest().methods[0], inputSchema: { type: 'string', pattern: 'x' } }] } ]
      const failures = []
      for (const candidate of cases) failures.push(await attempt(() => registry.register({ manifest: candidate, query: async () => ({}) })))
      const first = registry.register({ manifest: manifest(), query: async () => ({ value: 1 }) })
      failures.push(await attempt(() => registry.register({ manifest: manifest(), query: async () => ({ value: 2 }) })))
      registry.syncClientManifest([manifest('client')])
      const before = registry.list()
      failures.push(await attempt(() => registry.syncClientManifest([manifest('other'), manifest('other')])))
      const retained = registry.list()
      first(); first()
      registry.register({ manifest: manifest(), query: async () => ({ value: 2 }) }); first()
      return { failures, before, retained, after: registry.list() }
    }
    if (spec.recipe === 'host') {
      let result: any = { value: 1 }, afterCall: (() => void) | undefined
      const inputs: any[] = []
      registry.register({ manifest: manifest(), query: async (_method, input, context) => {
        inputs.push({ input: input === undefined ? { undefined: true } : input, owner: context.agent.id })
        afterCall?.(); return result
      } })
      const query = (input: any = undefined, signal = new AbortController().signal) => registry.query('host', 'probe', 'read', input, owner, signal)
      const nullInput = await attempt(() => query(null)), omitted = await attempt(() => query())
      const invalidInput = await attempt(() => query({ unexpected: 1 }))
      const detached = await query(); result.value = 2
      result = { value: 'bad' }; const invalidOutput = await attempt(() => query())
      result = { value: 1, negative: -0 }; const nonJson = await attempt(() => query())
      result = {}; result.self = result; const cyclic = await attempt(() => query())
      const controller = new AbortController(); afterCall = () => controller.abort('post-abort')
      const postAbort = await attempt(() => query(undefined, controller.signal))
      return { nullInput, omitted, invalidInput, detached, invalidOutput, nonJson, cyclic, postAbort, inputs,
        missingProvider: await attempt(() => registry.query('host', 'missing', 'read', undefined, owner, new AbortController().signal)),
        missingMethod: await attempt(() => registry.query('host', 'probe', 'missing', undefined, owner, new AbortController().signal)) }
    }
    registry.syncClientManifest([manifest('client')])
    const controller = new AbortController()
    if (spec.recipe === 'abort') {
      controller.abort('pre-abort')
      return { result: await attempt(() => registry.query('client', 'client', 'read', undefined, owner, controller.signal)), events }
    }
    let settled = false
    const pending = attempt(() => registry.query('client', 'client', 'read', spec.recipe === 'inflight' ? null : undefined, owner, controller.signal))
      .then(value => { settled = true; return value })
    await tick()
    const id = events[0].requestId
    if (spec.recipe === 'client') {
      const responses = [registry.resolveClientQuery(foreign, id, { ok: true, data: { value: 1 } }),
        registry.resolveClientQuery(owner, id, { ok: false, reason: 'failed', message: 'other page failed' } as any),
        registry.resolveClientQuery(owner, id, { ok: true, data: { value: 'bad' } } as any),
        registry.resolveClientQuery(owner, id, { ok: true, data: { value: 2 } }),
        registry.resolveClientQuery(owner, id, { ok: true, data: { value: 3 } })]
      const result = await pending; controller.abort('late')
      return { responses, result, events, acks }
    }
    if (spec.recipe === 'inflight') {
      const changed = manifest('client'); changed.methods[0].outputSchema = { type: 'string' }
      registry.syncClientManifest([changed])
      const accepted = registry.resolveClientQuery(owner, id, { ok: true, data: { value: 4 } })
      return { accepted, result: await pending, directory: registry.list(), events, acks }
    }
    if (spec.recipe === 'disposal') {
      await ctx.fiber.dispose(); await tick()
      const afterDispose = { pending: (registry as any).pending.size, settled, closed: events.filter(event => event.kind === 'closed').length }
      controller.abort('cleanup')
      return { afterDispose, result: await pending }
    }
    controller.abort('cancel')
    return { result: await pending, late: registry.resolveClientQuery(owner, id, { ok: true, data: { value: 1 } }), events, acks }
  } finally { await ctx.fiber.dispose() }
}
async function observe(spec: any): Promise<any> {
  if (spec.kind === 'schema') return { mode: spec.mode, result: await attempt(() => (spec.objectRoot ? assertObjectJsonSchema : assertSupportedJsonSchema)(recipe(spec, true))) }
  if (spec.kind === 'value') return { mode: spec.mode, violations: validateJsonSchemaValue(spec.schema, recipe(spec, false), spec.path ?? 'value') }
  if (spec.kind === 'forged') return { mode: spec.mode, result: await attempt(() => validateJsonSchemaValue(spec.schema, spec.value)) }
  if (spec.kind === 'registry') return { mode: spec.mode, ...await registryObservation(spec) }
  const ctx = new Context()
  ctx.provide('tools', { schemas: (agent: any) => [{ name: agent.id, parameters: empty }] } as any)
  const providers = hostInspectProviders(ctx).filter(provider => provider.manifest.id !== 'Builtin')
  try {
    const registry = new CordisInspectRegistryService(ctx)
    for (const provider of providers) registry.register(provider)
    return { mode: spec.mode, directory: registry.list(), services: [queryServiceApi(), ...SERVICE_API.map(row => queryServiceApi(row.key))],
      events: [queryEventApi(undefined, EVENT_API.filter(row => !row.name.startsWith('cordis/'))),
        ...EVENT_API.filter(row => !row.name.startsWith('cordis/')).map(row => queryEventApi(row.name))],
      missingService: await attempt(() => queryServiceApi('missing')), missingEvent: await attempt(() => queryEventApi('missing')),
      tools: await registry.query('host', 'Tool', 'listTools', undefined, owner, new AbortController().signal) }
  } finally { await ctx.fiber.dispose() }
}
it('records real pinned Inspect, schema and catalog behavior', async () => {
  const specs = JSON.parse(await readFile('scripts/oracles/inspect-cases.json', 'utf8'))
  const rows = []
  for (const spec of specs) rows.push(await observe(spec))
  expect(rows).toHaveLength(specs.length)
  await writeFile(process.env.INSPECT_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
})
