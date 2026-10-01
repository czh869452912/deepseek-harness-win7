import { it } from 'vitest'
import { readFile, writeFile } from 'node:fs/promises'
import { apply } from '../../reference/packages/extensions/tool-cordis/src/index.ts'
import { CORDIS_SYSTEM_PROMPT } from '../../reference/packages/extensions/tool-cordis/src/prompt.ts'
import { DynamicCordisRegistry } from '../../reference/packages/extensions/cordis-host-runner/src/registry.ts'
import { DynamicCordisRunnerService } from '../../reference/packages/extensions/cordis-host-runner/src/index.ts'

const detach = (value: any) => JSON.parse(JSON.stringify(value))
function environment(spec: any) {
  const fixture = detach(spec.fixture ?? {}), tools: any[] = [], hooks: any = {}, sections: any[] = [], calls: any[] = []
  const fiber: any = { inject: { present: {}, missing: {} } }
  fiber.parent = { fiber }
  const child: any = { parent: { fiber }, inject: {} }
  const foreign: any = { inject: {} }
  foreign.parent = { fiber: foreign }
  const store: any = { [Symbol()]: { name: 'zeta', fiber }, [Symbol()]: { name: 'alpha', fiber: child },
    [Symbol()]: { name: 'foreign', fiber: foreign } }
  if (spec.live) for (const row of fixture.snapshot ?? []) if (row.activeRun) row.activeRun.fiber = fiber
  const runner: any = {
    listPlugins: () => fixture.plugins ?? [], inspectPlugin: () => fixture.plugin,
    inspectPackage: () => fixture.inspected, snapshot: () => fixture.snapshot ?? [],
    reference: (_agent: any, id: string) => { calls.push(id); return fixture.references?.[id] },
    define: (request: any) => fixture.receipt,
    run: async () => fixture.receipt, stop: async () => fixture.receipt, undefine: async () => fixture.receipt,
  }
  const ctx: any = { reflect: { store }, dynamicCordisRunner: runner,
    tools: { register: (tool: any) => tools.push(tool) },
    systemPrompt: { section: (section: any) => sections.push(section) },
    cordisInspect: { register: () => () => {}, list: () => [], query: async () => fixture.data },
    effect: (callback: any) => callback(), on: (name: string, fn: any) => { hooks[name] = fn },
    get: (name: string) => name === 'present' ? 0 : undefined,
  }
  apply(ctx)
  return { tools, hooks, sections, calls }
}

export async function observe(spec: any) {
  const env = environment(spec)
  if (spec.kind === 'presentation') return env.tools.find(tool => tool.name === spec.tool).presentCall(spec.args) ?? null
  if (spec.kind === 'execute') {
    const tool = env.tools.find(tool => tool.name === spec.tool)
    const value = await tool.execute(spec.args, { ...spec.noAgent ? {} : { agent: { id: 'owner' } }, signal: new AbortController().signal })
    return { value, render: tool.output.render(spec.args, value), meta: tool.output.presentationMeta?.(spec.args, value) ?? null }
  }
  if (spec.kind === 'render-error') {
    const tool = env.tools.find(tool => tool.name === 'cordis_run')
    return tool.output.presentationMeta({}, spec.value)
  }
  if (spec.kind === 'pre-step') {
    const controller = new AbortController()
    const decision = await env.hooks['agent/pre-step']({ agent: { id: 'owner' }, messages: spec.messages, signal: controller.signal }, async () => {
      if (spec.abort) controller.abort(new Error('stop reference'))
      return detach(spec.decision)
    })
    const { messages, ...rest } = decision
    return { ...rest, messages: messages?.map((message: any) => {
      if (message.source?.plugin !== 'tool-cordis') return message
      const { id, ...content } = message
      if (typeof id !== 'string') throw new Error('injected message has no identity')
      return content
    }), lookups: env.calls }
  }
  if (spec.kind === 'runner-views' || spec.kind === 'plan') {
    const registry = new DynamicCordisRegistry()
    for (const row of spec.plugins) {
      registry.add({ ...row, sessionId: row.agentId, packages: new Map(row.packages.map((p: any) => [p.packageId,
        { ...p, ...p.code.host === undefined ? {} : { hostCode: p.code.host }, ...p.code.client === undefined ? {} : { clientCode: p.code.client } }])),
        approvedClientPackages: new Set(), clientVersionUpdatesApproved: false } as any)
    }
    const runner: any = Object.create(DynamicCordisRunnerService.prototype)
    runner.registry = registry
    if (spec.kind === 'plan') {
      runner.starting = new Map(spec.starting ? [['theme-1', Promise.resolve()]] : [])
      const result = runner.resolvePlan({ id: spec.agentId ?? 'owner' }, spec.pluginId ?? 'theme-1', spec.packageId ?? 'pkg-2', spec.activationMode, spec.attach ?? false)
      return result.ok ? { ok: true } : { ok: false, response: result.response }
    }
    const agent: any = { id: spec.agentId ?? 'owner' }
    return (runner as any)[spec.method](agent, ...spec.ids ?? [])
  }
  if (spec.kind === 'mints') {
    const registry = new DynamicCordisRegistry()
    return [registry.mintPluginId('theme'), registry.mintPluginId('panel'), registry.mintPackageId(),
      registry.mintPackageId(), registry.mintPluginRunId(), registry.mintPluginRunId(), registry.mintApprovalRequestId(), registry.mintPluginId('theme')]
  }
  throw new Error('unknown observation ' + spec.kind)
}

it('observes unchanged original tool-cordis definitions and callbacks', async () => {
  const specs = JSON.parse(await readFile('scripts/oracles/cordis-tools-cases.json', 'utf8'))
  const cases = []
  for (const spec of specs) {
    try { cases.push({ mode: spec.mode, value: await observe(spec) ?? null }) }
    catch (error: any) { cases.push({ mode: spec.mode, error: { message: error.message } }) }
  }
  const env = environment({})
  const definitions = env.tools.map(({ name, description, parameters, output }: any) => ({ name, description, parameters, outputSchema: output.schema }))
  await writeFile(process.env.CORDIS_TOOLS_OUTPUT!, JSON.stringify({ cases, definitions, prompt: CORDIS_SYSTEM_PROMPT, order: env.sections[0].order }, null, 2))
})
