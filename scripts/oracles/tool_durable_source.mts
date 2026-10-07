import {readFile, writeFile} from 'node:fs/promises'
import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {fileURLToPath} from 'node:url'
import path from 'node:path'
import {Context} from '../../reference/vendor/cordis/src/index.ts'
import Llm, {HarnessError} from '../../reference/packages/llm/llm/src/index.ts'
import Sessions, {SessionId} from '../../reference/packages/core/session/src/index.ts'
import Tools from '../../reference/packages/core/tools/src/index.ts'
import Prompt from '../../reference/packages/core/system-prompt/src/index.ts'
import Agents from '../../reference/packages/core/agent/src/index.ts'
import Loop from '../../reference/packages/core/agent-loop/src/index.ts'
import {executeToolCalls} from '../../reference/packages/core/agent-loop/src/tool-calls.ts'

const here = path.dirname(fileURLToPath(import.meta.url))
const cases = JSON.parse(await readFile(path.join(here, 'tool-durable-cases.json'), 'utf8'))
const originalNow = Date.now
Date.now = () => 1791331200000
const rows: any[] = []
try {
  for (const spec of cases) {
    const ctx = new Context()
    let handle: any
    try {
      for (const plugin of [Llm, Sessions, Tools, Prompt, Agents]) await ctx.plugin(plugin)
      await ctx.plugin(Loop, {agents:[], maxParallelToolCalls:1})
      handle = await ctx.agents.create({sessionId:SessionId('durable-' + spec.name)})
      const agent = handle.agent
      const controller = new AbortController()
      const calls: string[] = []
      const publicResults: any[] = []
      ctx.tools.register({name:'probe', description:'Controlled complete durable result.',
        parameters:{type:'object', properties:{identity:{type:'string'}}, required:['identity'], additionalProperties:false},
        isConcurrencySafe:() => false,
        output:{schema:{type:'string'}, render:(_arguments: any, value: any) => [{type:'text', text:value}],
          ...Object.hasOwn(spec, 'meta') ? {presentationMeta:() => spec.meta} : {}},
        async execute(arguments_: any) {
          calls.push(arguments_.identity)
          if (spec.abort === 'body') controller.abort()
          if (spec.throw === 'plain') throw new Error('plain failure')
          if (spec.throw === 'typed') throw new HarnessError('typed failure', 'CONTROLLED_TYPED')
          return 'body value'
        },
      })
      ctx.on('tools/result', (_execution: any, result: any) => {publicResults.push(structuredClone(result))})
      if (spec.abort === 'before') controller.abort()
      const outcome = await ctx.agents.withInitiator(agent, () => executeToolCalls(agent.ctx, 1, 1,
        ['c1','c2','c3'].map(identity => ({type:'tool-call' as const, id:identity as any,
          name:'probe', arguments:JSON.stringify({identity})})), controller.signal, () => {}))
      rows.push({name:spec.name, calls, outcome, publicResults,
        events:structuredClone(agent.session.events.filter(event => event.type === 'tool/call' || event.type === 'tool/result'))})
    } finally {
      if (handle) await handle.dispose()
      await ctx.fiber.dispose()
    }
  }
} finally {
  Date.now = originalNow
}
const fixtureSha256 = createHash('sha256').update(await readFile(fileURLToPath(import.meta.url))).digest('hex')
const sourceCommit = execFileSync('git', ['-C', path.resolve(here, '../../reference'), 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim()
await writeFile(process.env.DSH_TOOL_DURABLE_OUTPUT!, JSON.stringify({sourceCommit, node:process.version, fixtureSha256, rows}, null, 2) + '\n', {flag:'wx'})
