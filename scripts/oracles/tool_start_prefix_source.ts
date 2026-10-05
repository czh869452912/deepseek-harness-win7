import {Context} from '@deepseek-ai/cordis'
import Llm from '@deepseek-ai/dsh-llm'
import Sessions, {SessionId} from '@deepseek-ai/dsh-session'
import Tools, {TOOL_RUNTIME_SCHEDULER} from '@deepseek-ai/dsh-tools'
import Prompt from '@deepseek-ai/dsh-system-prompt'
import Agents from '@deepseek-ai/dsh-agent'
import Loop from '@deepseek-ai/dsh-agent-loop'
import {executeToolCalls} from '../../reference/packages/core/agent-loop/src/tool-calls.ts'

export async function observePrefixes() {
  const observations: any[] = []
  for (const implementation of ['custom-future', 'canonical-body']) {
    for (const action of ['none', 'abort', 'reclassify', 'throw']) {
      const ctx = new Context()
      await ctx.plugin(Llm)
      await ctx.plugin(Sessions)
      await ctx.plugin(Tools)
      await ctx.plugin(Prompt)
      await ctx.plugin(Agents)
      await ctx.plugin(Loop, {agents:[], maxParallelToolCalls:3})
      const handle = await ctx.agents.create({sessionId:SessionId(implementation + '-' + action)})
      const agent = handle.agent, signal = new AbortController()
      const prefixes: string[] = [], preparations: any[] = []
      const firstEntered = Promise.withResolvers<void>(), failureEntered = Promise.withResolvers<void>()
      const releases = Object.fromEntries(['c1','c2','c3'].map(identity => [identity, Promise.withResolvers<any>()]))
      const failure = new Error('prefix failure')
      let secondParallel = true, settled = false
      const enter = (identity: string) => {
        prefixes.push(identity)
        if (identity === 'c1') {
          if (action === 'abort') signal.abort()
          if (action === 'reclassify') secondParallel = false
          firstEntered.resolve()
        }
        if (identity === 'c2' && action === 'throw') {failureEntered.resolve(); throw failure}
      }
      ctx.tools.register({name:'probe', description:'probe',
        parameters:{type:'object', properties:{identity:{type:'string'}}, required:['identity']},
        isConcurrencySafe:(arguments_: any) => arguments_.identity !== 'c2' || secondParallel,
        output:{schema:{type:'string'}, render:(_arguments: any, value: any) => [{type:'text', text:value}]},
        async execute(arguments_: any) {
          enter(arguments_.identity)
          return await releases[arguments_.identity].promise
        },
      })
      ctx.on('tools/pre-execute', (execution: any, next: any) => {
        preparations.push({callId:String(execution.callId), prefixes:[...prefixes]})
        return next()
      })
      if (implementation === 'custom-future') {
        ctx.tools[TOOL_RUNTIME_SCHEDULER].dispatch = (execution: any) => {
          enter(String(execution.callId))
          return releases[String(execution.callId)].promise
        }
      }
      let terminal: any = null
      const pending = ctx.agents.withInitiator(agent, () => executeToolCalls(agent.ctx,1,1,
        ['c1','c2','c3'].map(identity => ({type:'tool-call' as const, id:identity as any, name:'probe', arguments:JSON.stringify({identity})})),
        signal.signal, () => {})).then(result => {settled = true; return result}, error => {
          settled = true; terminal = {message:error.message, sameFailure:error === failure}; return null
        })
      try {
        await firstEntered.promise
        if (action === 'throw') await failureEntered.promise
        const held = {settled}
        for (const identity of ['c1','c2','c3']) {
          releases[identity].resolve(implementation === 'custom-future'
            ? {kind:'final-result', result:{content:[{type:'text', text:identity}], isError:false}} : identity)
        }
        const result = await pending
        const events = agent.session.events
        observations.push({name:implementation + '-' + action, prefixes, preparations, held, terminal, result,
          calls:events.filter(event => event.type === 'tool/call').map((event: any) => event.data.callId),
          results:events.filter(event => event.type === 'tool/result').map((event: any) => ({
            callId:event.data.message.source.callId, isError:event.data.message.content[0].isError,
            code:event.data.error?.code ?? null,
          })),
        })
      } finally {
        for (const identity of ['c1','c2','c3']) releases[identity].resolve(null)
        await pending
        await handle.dispose()
        await ctx.fiber.dispose()
      }
    }
  }
  return observations
}
