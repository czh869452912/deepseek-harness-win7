import {writeFile, readFile} from 'node:fs/promises'
import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {createHash} from 'node:crypto'
import {Context, FiberState} from '../../reference/vendor/cordis/src/index.ts'
import Llm from '../../reference/packages/llm/llm/src/index.ts'
import Sessions, {SessionId} from '../../reference/packages/core/session/src/index.ts'
import Tools from '../../reference/packages/core/tools/src/index.ts'
import Prompt from '../../reference/packages/core/system-prompt/src/index.ts'
import Agents from '../../reference/packages/core/agent/src/index.ts'
import Loop from '../../reference/packages/core/agent-loop/src/index.ts'

const services = ['agents','sessions','llm','tools','systemPrompt'] as const
const providers = {agents:Agents, sessions:Sessions, llm:Llm, tools:Tools, systemPrompt:Prompt}
const rows: any[] = []
const settle = async () => {await new Promise(done => setImmediate(done)); await new Promise(done => setImmediate(done))}
const project = (ctx: Context, fiber: any) => ({active:fiber.state === FiberState.ACTIVE,
  pending:fiber.state === FiberState.PENDING, loop:ctx.get('agentLoop') !== undefined,
  services:Object.fromEntries(services.map(name => [name,ctx.get(name) !== undefined]))})
{
  const ctx = new Context()
  try {
    const loop = await ctx.plugin(Loop, {agents:[]})
    rows.push({name:'initial-missing', ...project(ctx, loop)})
    for (const name of ['systemPrompt','tools','llm','agents','sessions'] as const) {
      await ctx.plugin(providers[name])
      await settle()
      rows.push({name:'provide-' + name, ...project(ctx, loop)})
    }
  } finally {await ctx.fiber.dispose()}
}
for (const name of services) {
  const ctx = new Context()
  let handle: any
  try {
    const fibers = new Map()
    for (const service of services) fibers.set(service, await ctx.plugin(providers[service]))
    const loop = await ctx.plugin(Loop, {agents:[]})
    await settle()
    const factory = ctx.agentLoop
    const registry = ctx.agents
    const id = SessionId('dependency-' + name)
    handle = await registry.create({sessionId:id})
    rows.push({name:name + '/before-loss', ...project(ctx, loop), published:registry.get(id) === handle.agent})
    await fibers.get(name).dispose()
    await settle()
    rows.push({name:name + '/after-loss', ...project(ctx, loop), published:registry.get(id) !== undefined})
    let oldFactory: any
    try {
      const late = await factory.createAgent(ctx, {sessionId:SessionId('late-' + name)})
      await late.dispose()
      oldFactory = {accepted:true}
    } catch (error: any) {oldFactory = {message:error.message}}
    rows.push({name:name + '/retired-factory', result:oldFactory})
    await ctx.plugin(providers[name])
    await settle()
    rows.push({name:name + '/restored', ...project(ctx, loop), replacement:ctx.agentLoop !== factory})
    const current = await ctx.agents.create({sessionId:SessionId('restored-' + name)})
    rows.push({name:name + '/restored-create', published:ctx.agents.get(current.agent.id) === current.agent})
    await current.dispose()
    await loop.dispose()
    await settle()
    rows.push({name:name + '/final-disposal', loop:ctx.get('agentLoop') !== undefined})
  } finally {
    if (handle) await handle.dispose()
    await ctx.fiber.dispose()
  }
}
await writeFile(process.env.DSH_AGENT_DEPENDENCIES_OUTPUT!, JSON.stringify({
  sourceCommit:execFileSync('git',['-C',fileURLToPath(new URL('../../reference/', import.meta.url)),'rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  fixtureSha256:createHash('sha256').update(await readFile(fileURLToPath(import.meta.url))).digest('hex'),
  node:process.version, rows}, null, 2) + '\n', {flag:'wx'})
