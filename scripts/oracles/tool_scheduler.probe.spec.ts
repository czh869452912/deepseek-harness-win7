import {it} from 'vitest'
import {writeFile} from 'node:fs/promises'
import {Context} from '@deepseek-ai/cordis'
import Llm, {ToolCallId, createUserMessage} from '@deepseek-ai/dsh-llm'
import {MockAdapter,textResponse} from '../../reference/packages/core/agent-loop/tests/mock-adapter.ts'
import Sessions, {SessionId} from '@deepseek-ai/dsh-session'
import Tools, {defineContentToolFixture} from '@deepseek-ai/dsh-tools'
import Prompt from '@deepseek-ai/dsh-system-prompt'
import Agents from '@deepseek-ai/dsh-agent'
import Loop from '@deepseek-ai/dsh-agent-loop'
import {SettingsProvider} from '@deepseek-ai/dsh-settings'

class MemorySettings extends SettingsProvider {
  doc: Record<string,unknown> = {}
  get writable() {return true}
  protected async load() {return structuredClone(this.doc)}
  protected async persist(namespace: any, section: any) {this.doc = {...this.doc,[namespace]:structuredClone(section)}}
}

async function boot(cap: number, settings = false) {
  const ctx = new Context()
  await ctx.plugin(Llm)
  await ctx.plugin(Sessions)
  await ctx.plugin(Tools)
  await ctx.plugin(Prompt)
  await ctx.plugin(Agents)
  const settingsFiber = settings ? await ctx.plugin(MemorySettings) : undefined
  const loopFiber = await ctx.plugin(Loop,{agents:[],maxParallelToolCalls:cap})
  return {ctx,settingsFiber,loopFiber}
}

it('observes actual original caps, settings ownership and factory model consumers',async () => {
  const rows: any[] = []
  for (const [name,value] of [['default',undefined],['one',1],['whole-float',2.0],['zero',0],['negative',-1],['fraction',1.5],['boolean',true],['text','2'],['nan',NaN],['infinite',Infinity]] as const) {
    const ctx = new Context()
    try {
      await ctx.plugin(Llm)
      await ctx.plugin(Sessions)
      await ctx.plugin(Tools)
      await ctx.plugin(Prompt)
      await ctx.plugin(Agents)
      const loop = new Loop(ctx,{agents:[],...value === undefined ? {} : {maxParallelToolCalls:value as any}})
      rows.push({name:'cap-'+name,value:loop.config.maxParallelToolCalls})
    } catch (error: any) {rows.push({name:'cap-'+name,error:error.message})}
    finally {await ctx.fiber.dispose()}
  }
  for (const [name,config,expected] of [
    ['config-empty-session',{agents:[{id:'main',sessionId:''}]},'expected string length >= 1'],
    ['config-boolean-max-tokens',{agents:[{id:'main',maxTokens:true}]},'expected number but got true'],
  ] as const) {
    const ctx = new Context(), published: boolean[] = []
    ctx.on('agent/created',() => {published.push(true)})
    await ctx.plugin(Llm);await ctx.plugin(Sessions);await ctx.plugin(Tools);await ctx.plugin(Prompt);await ctx.plugin(Agents)
    try {
      await ctx.plugin(Loop,config as any)
      rows.push({name,admitted:true,published})
    } catch (error: any) {rows.push({name,error:error.name,expected:error.message.includes(expected),published})}
    finally {await ctx.fiber.dispose()}
  }
  {
    const {ctx,settingsFiber,loopFiber} = await boot(4,true)
    const cap = () => ctx.agentLoop.config.maxParallelToolCalls
    try {
      rows.push({name:'settings-entry',value:cap(),keys:Object.keys(ctx.settings.describe().find(row => row.ns === 'agent-loop')!.value as object)})
      await ctx.settings.update('agent-loop' as any,{maxParallelToolCalls:1})
      rows.push({name:'settings-updated',value:cap(),agents:ctx.agentLoop.config.agents})
      let refused = false
      try {await ctx.settings.update('agent-loop' as any,{maxParallelToolCalls:0})} catch {refused = true}
      rows.push({name:'settings-refused',refused,value:cap()})
      await settingsFiber!.dispose()
      rows.push({name:'settings-detached',value:cap()})
      await ctx.plugin(MemorySettings)
      await ctx.settings.update('agent-loop' as any,{maxParallelToolCalls:2})
      rows.push({name:'settings-replaced',value:cap()})
      await loopFiber.dispose()
      rows.push({name:'settings-unloaded',present:ctx.settings.describe().some(row => row.ns === 'agent-loop')})
    } finally {await ctx.fiber.dispose()}
  }
  {
    const {ctx} = await boot(2,true)
    const chunks: any[] = []
    for (let index=0; index<7; index++) chunks.push(
      {type:'block-start',index,blockType:'tool-call'},
      {type:'block-end',index,block:{type:'tool-call',id:ToolCallId('call-'+index),name:'gated',arguments:JSON.stringify({index})}})
    chunks.push({type:'finish',reason:{kind:'tool-calls'}})
    const adapter = new MockAdapter([chunks,textResponse('done')])
    ctx.llm.registerAdapter(['mock'],adapter)
    const entered = Array.from({length:7},() => Promise.withResolvers<void>())
    const release = Array.from({length:7},() => Promise.withResolvers<void>())
    const active = [0,0], peaks = [0,0], started: number[] = []
    ctx.tools.register(defineContentToolFixture({name:'gated',description:'gated',parameters:{index:{type:'number',required:true}},
      isConcurrencySafe:argumentsValue => argumentsValue.index !== 3,
      async execute(argumentsValue) {
        const index = argumentsValue.index, group = index < 3 ? 0 : 1
        if (index !== 3) {active[group]++;peaks[group] = Math.max(peaks[group],active[group])}
        started.push(index);entered[index].resolve()
        try {
          if (index !== 3) await release[index].promise
          if (index === 0) await ctx.settings.update('agent-loop' as any,{maxParallelToolCalls:1})
          return [{type:'text',text:'done-'+index}]
        } finally {if (index !== 3) active[group]--}
      }}))
    const handle = await ctx.agents.create({sessionId:SessionId('group-snapshot'),agentOptions:{provider:'mock',model:'mock'}})
    try {
      const idle = new Promise<void>(resolve => {const detach = ctx.on('agent/status',({agent,status}) => {
        if (agent === handle.agent && status === 'idle') {detach();resolve()}
      })})
      handle.agent.followup(createUserMessage({content:[{type:'text',text:'go'}],source:{kind:'user'}}))
      await entered[1].promise
      const initial = [...started]
      release[0].resolve()
      await entered[2].promise
      const continuation = [...started]
      release[1].resolve();release[2].resolve()
      for (let index=4;index<7;index++) {await entered[index].promise;release[index].resolve()}
      await idle
      rows.push({name:'model-group-snapshot',initial,continuation,peaks,started,cap:ctx.agentLoop.config.maxParallelToolCalls,
        requests:handle.agent.session.events.filter(event => event.type === 'assistant/message').length,
        results:handle.agent.session.events.filter(event => event.type === 'tool/result').map((event: any) => event.data.message.source.callId)})
    } finally {release.forEach(gate => gate.resolve());await handle.dispose();await ctx.fiber.dispose()}
  }
  for (const cap of [1,2,10]) {
    const {ctx} = await boot(cap)
    const chunks: any[] = []
    for (let index=0; index<12; index++) chunks.push(
      {type:'block-start',index,blockType:'tool-call'},
      {type:'block-end',index,block:{type:'tool-call',id:ToolCallId('call-'+index),name:'gated',arguments:JSON.stringify({index})}})
    chunks.push({type:'finish',reason:{kind:'tool-calls'}})
    const adapter = new MockAdapter([chunks,textResponse('done')])
    ctx.llm.registerAdapter(['mock'],adapter)
    const entered = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
    let active = 0, peak = 0
    const started: number[] = []
    ctx.tools.register(defineContentToolFixture({name:'gated',description:'gated',parameters:{index:{type:'number',required:true}},
      isConcurrencySafe:() => true,async execute(argumentsValue) {
        active++; peak = Math.max(peak,active); started.push(argumentsValue.index)
        if (started.length === cap) entered.resolve()
        try {await release.promise; return [{type:'text',text:'done-'+argumentsValue.index}]} finally {active--}
      }}))
    const handle = await ctx.agents.create({sessionId:SessionId('pool-'+cap),agentOptions:{provider:'mock',model:'mock'}})
    try {
      const idle = new Promise<void>(resolve => {const detach = ctx.on('agent/status',({agent,status}) => {
        if (agent === handle.agent && status === 'idle') {detach();resolve()}
      })})
      handle.agent.followup(createUserMessage({content:[{type:'text',text:'go'}],source:{kind:'user'}}))
      await entered.promise
      release.resolve()
      await idle
      rows.push({name:'model-pool-'+cap,peak,started,
        requests:handle.agent.session.events.filter(event => event.type === 'assistant/message').length,
        results:handle.agent.session.events.filter(event => event.type === 'tool/result').map((event: any) => ({
          callId:event.data.message.source.callId,isError:event.data.message.content[0].isError}))})
    } finally {release.resolve();await handle.dispose();await ctx.fiber.dispose()}
  }
  await writeFile(process.env.TOOL_SCHEDULER_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
},15000)
