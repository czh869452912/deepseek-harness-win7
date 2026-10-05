import {it} from 'vitest'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import Llm from '@deepseek-ai/dsh-llm'
import Sessions, {SessionId} from '@deepseek-ai/dsh-session'
import Tools, {TOOL_RUNTIME_SCHEDULER} from '@deepseek-ai/dsh-tools'
import Prompt from '@deepseek-ai/dsh-system-prompt'
import Agents from '@deepseek-ai/dsh-agent'
import Loop from '@deepseek-ai/dsh-agent-loop'
import {executeToolCalls} from '../../reference/packages/core/agent-loop/src/tool-calls.ts'

async function harness(identity: string) {
  const ctx = new Context()
  await ctx.plugin(Llm)
  await ctx.plugin(Sessions)
  await ctx.plugin(Tools)
  await ctx.plugin(Prompt)
  await ctx.plugin(Agents)
  await ctx.plugin(Loop, {agents:[], maxParallelToolCalls:3})
  const handle = await ctx.agents.create({sessionId:SessionId(identity)})
  return {ctx, handle, agent:handle.agent}
}

function results(agent: any) {
  return agent.session.events.filter((event: any) => event.type === 'tool/result').map((event: any) => ({
    callId:event.data.message.source.callId, content:event.data.message.content[0].content,
    isError:event.data.message.content[0].isError,
  }))
}

it('observes actual final-result finishing and owned scheduler failure boundaries', async () => {
  const rows: any[] = []
  for (const mode of ['pre-error','around-error','pre-deny','success']) {
    const {ctx, handle, agent} = await harness(mode)
    const phases: string[] = []
    ctx.tools.register({name:'probe', description:'probe', parameters:{},
      output:{schema:{type:'string'}, render:(_arguments: any, value: any) => [{type:'text', text:value}]},
      async execute() {phases.push('body'); return 'body result'},
      finalizeContent(_execution: any, _result: any) {phases.push('finish'); return [{type:'text',text:'finalized'}]},
    })
    ctx.on('tools/pre-execute', (_execution: any, next: any) => {
      phases.push('pre')
      if (mode === 'pre-error') throw new Error('pre failed')
      return mode === 'pre-deny' ? {kind:'deny',reason:'denied'} : next()
    })
    ctx.on('tools/execute', (_execution: any, next: any) => {
      phases.push('around')
      if (mode === 'around-error') throw new Error('around failed')
      return next()
    })
    ctx.on('tools/post-execute', (_execution: any, _result: any, next: any) => {phases.push('post'); return next()})
    ctx.on('tools/result', () => {phases.push('notify')})
    await ctx.agents.withInitiator(agent, () => executeToolCalls(agent.ctx, 1, 1,
      [{type:'tool-call',id:'c1' as any,name:'probe',arguments:'{}'}],new AbortController().signal,() => {}))
    rows.push({mode, phases, results:results(agent)})
    await handle.dispose()
    await ctx.fiber.dispose()
  }
  for (const siblingBeforePrepare of [false, true]) {
    const {ctx, handle, agent} = await harness('failure-during-prepare-' + siblingBeforePrepare)
    const entered = Promise.withResolvers<void>(), releasePrepare = Promise.withResolvers<void>()
    const releaseFirst = Promise.withResolvers<any>(), releaseSibling = Promise.withResolvers<any>()
    const phases: string[] = []
    const scheduler = ctx.tools[TOOL_RUNTIME_SCHEDULER]
    const originalPrepare = scheduler.prepare.bind(scheduler)
    ctx.tools.register({name:'probe',description:'probe',parameters:{},isConcurrencySafe:() => true,
      output:{schema:{type:'string'},render:(_arguments: any, value: any) => [{type:'text',text:value}]},
      async execute() {return 'unused'},
    })
    scheduler.prepare = async (execution: any) => {
      const prepared = await originalPrepare(execution)
      if (execution.callId === 'c3') {phases.push('prepare-c3'); entered.resolve(); await releasePrepare.promise}
      return prepared
    }
    scheduler.dispatch = (execution: any) => {
      phases.push('dispatch-' + execution.callId)
      if (execution.callId === 'c1') return releaseFirst.promise
      if (execution.callId === 'c2') return releaseSibling.promise
      return Promise.resolve({kind:'final-result',result:{content:[],isError:false}})
    }
    const first = new Error('first failure'), sibling = new Error('sibling failure')
    let settled = false
    const pending = ctx.agents.withInitiator(agent, () => executeToolCalls(agent.ctx,1,1,
      ['c1','c2','c3'].map(id => ({type:'tool-call' as const,id:id as any,name:'probe',arguments:'{}'})),
      new AbortController().signal,() => {})).then(() => {settled=true; return 'unexpected success'},
      (error: any) => {settled=true; return error.message})
    await entered.promise
    releaseFirst.reject(first)
    await new Promise(resolve => setImmediate(resolve))
    if (siblingBeforePrepare) {
      releaseSibling.reject(sibling)
      await new Promise(resolve => setImmediate(resolve))
    }
    const held = {settled, dispatches:phases.filter(phase => phase.startsWith('dispatch-'))}
    releasePrepare.resolve()
    await new Promise(resolve => setImmediate(resolve))
    const before = {settled, phases:[...phases], calls:agent.session.events.filter(event => event.type === 'tool/call').map((event: any) => event.data.callId)}
    if (!siblingBeforePrepare) releaseSibling.reject(sibling)
    rows.push({mode:'failure-during-prepare',siblingBeforePrepare,held,before,error:await pending,phases,results:results(agent)})
    await handle.dispose()
    await ctx.fiber.dispose()
  }
  writeFileSync(process.env.TOOL_SCHEDULER_RESEARCH_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
},15000)
