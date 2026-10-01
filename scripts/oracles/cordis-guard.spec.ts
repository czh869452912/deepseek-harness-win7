import { it } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { sandboxDefineTool, sandboxRegisterTool, guardedPlugin, normalizeHandler } from '../../reference/packages/extensions/cordis-host-runner/src/guard.ts'
import { setup } from '../../reference/packages/extensions/cordis-host-runner/tests/helpers.ts'

function value(spec: any): any {
  switch (spec.recipe) {
    case 'undefined': return undefined
    case 'nan': return NaN
    case 'negative-zero': return -0
    case 'function': return () => {}
    case 'cycle': { const result: any = {}; result.again = result; return result }
    case 'decorated': { const result: any = [1]; result.hidden = true; return result }
    case 'nested-undefined': return { nested: [1, { invalid: undefined }] }
    case 'preview': return ['x'.repeat(200)]
    case 'unicode-preview': return ['😀'.repeat(100)]
    default: return spec.value
  }
}
function definition(parameters: any = {}, schema: any = { type: 'json' }) {
  return { name: 'guard_probe', description: 'Actual guard', parameters,
    output: { schema, render: (_args: any, _value: any): any => [], presentationMeta: (_args: any, v: any): any => v },
    execute: async (_args: any, exec: any): Promise<any> => null }
}
const project = (tool: any) => ({ name: tool.name, description: tool.description, parameters: tool.parameters, outputSchema: tool.output.schema })
const observed = (value: any) => value === undefined ? { undefined: true } : value
export async function observe(spec: any): Promise<any> {
  let options: any = definition(), tool: any
  if (spec.kind === 'parameters') return project(sandboxDefineTool(definition(spec.value)))
  if (spec.kind === 'schema') return project(sandboxDefineTool(definition({}, spec.value)))
  if (spec.kind === 'invalid-option') {
    if (spec.value === 'options') options = 42
    else if (spec.value === 'output') options.output = null
    else if (spec.value === 'timeout') options.timeoutMs = false
    else if (spec.value === 'execute') options.execute = true
    else options.output[spec.value] = true
    return project(sandboxDefineTool(options))
  }
  if (spec.kind === 'execute') { options.execute = async () => value(spec); return observed(await sandboxDefineTool(options).execute({}, {} as any)) }
  if (spec.kind === 'render' || spec.kind === 'meta') {
    const key = spec.kind === 'render' ? 'render' : 'presentationMeta'
    options.output[key] = () => value(spec)
    return observed((sandboxDefineTool(options).output as any)[key]({}, null))
  }
  if (spec.kind === 'handler') return observed(await normalizeHandler(spec.method ?? 'read', spec.invalidCallback ? false : () => value(spec)).handler({}))
  if (spec.kind === 'soft') {
    options = definition({ x: { type: 'string', required: true } })
    options.presentCall = () => ({ title: 'call' }); options.presentResult = () => ({ title: 'result' }); options.isConcurrencySafe = () => true
    tool = sandboxDefineTool(options); const args = spec.valid ? { x: 'ok' } : {}
    return { call: observed(tool.presentCall(args)), result: observed(tool.presentResult(args, {})), concurrency: tool.isConcurrencySafe(args) }
  }
  if (spec.kind === 'depth') {
    let schema: any = { type: 'string' }
    for (let i = 0; i < spec.value; i++) schema = { type: 'array', items: schema }
    tool = sandboxDefineTool(definition({ x: schema }, schema))
    let node = tool.output.schema, depth = 0
    while (node.type === 'array') { depth++; node = node.items }
    return { depth, leaf: node }
  }
  const { ctx } = await setup()
  try {
    if (spec.kind === 'marker') {
      tool = sandboxDefineTool(options)
      sandboxRegisterTool(ctx, spec.variant === 'real' ? tool : spec.variant === 'spread' ? { ...tool } : options)
      return { schemas: ctx.tools.schemas() }
    }
    if (spec.kind === 'facade') {
      let facade: any
      const reports: string[] = []
      ctx.provide('demo', { value: 'ready', sync: () => ctx, async: async () => ctx, context: ctx })
      ctx.provide('directContext', ctx)
      ctx.provide('callable', spec.operation === 'callable-async-context' ? async () => ctx : spec.operation === 'callable-data' ? () => 'ready' : () => ctx)
      await ctx.plugin(guardedPlugin({ inject: spec.operation === 'tools-declared' ? ['demo', 'tools'] : ['demo'], apply(guarded: any) { facade = guarded } }, error => reports.push(error.message)))
      const op = spec.operation
      let result: any
      try {
        if (op === 'write') { facade.stash = 1; result = null }
        else if (op === 'undeclared') result = facade.directContext
        else if (op === 'optional') result = facade.get('absent') ?? null
        else if (op === 'declared') result = facade.demo.value
        else if (op === 'service-write') { facade.demo.value = 'changed'; result = facade.demo.value }
        else if (op === 'tools-view' || op === 'tools-declared') {
          sandboxRegisterTool(ctx, sandboxDefineTool(options))
          result = { get: facade.tools.get('guard_probe'), schemas: facade.get('tools').schemas(), execute: 'execute' in facade.tools.get('guard_probe') }
        } else if (op === 'has') result = ['tools','get','on','timer','timeout','demo','root','fiber','missing'].map(key => key in facade)
        else if (op === 'sync-context') result = facade.demo.sync()
        else if (op === 'index-context') result = facade.demo['sync']()
        else if (op === 'async-context') result = await facade.demo.async()
        else if (op === 'property-context') result = facade.demo.context
        else if (op === 'direct-context') result = facade.get('directContext')
        else if (op === 'callable-data') result = facade.get('callable')()
        else if (op === 'callable-context' || op === 'callable-async-context') result = { escaped: (await facade.get('callable')()) === ctx }
        else result = facade[op]
        return { value: observed(result), reports }
      } catch (error: any) { return { error: { message: error.message }, reports } }
    }
    throw new Error('unknown kind')
  } finally { await ctx.fiber.dispose() }
}

it('records unchanged original Host Guard exports', async () => {
  const specs = JSON.parse(await readFile('scripts/oracles/cordis-guard-cases.json', 'utf8')), cases = []
  for (const spec of specs) {
    try { cases.push({ mode: spec.mode, value: await observe(spec) }) }
    catch (error: any) { cases.push({ mode: spec.mode, error: { message: error.message, ...(error.code ? { code: error.code, name: error.name, violations: error.violations } : {}) } }) }
  }
  await writeFile(process.env.CORDIS_GUARD_OUTPUT!, JSON.stringify(cases, null, 2))
}, 60000)
