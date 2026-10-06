import { expect, it } from 'vitest'
import { createServer } from 'node:http'
import { writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { Context } from '@deepseek-ai/cordis'
import AgentLoop from '@deepseek-ai/dsh-agent-loop'
import { SessionId } from '@deepseek-ai/dsh-session'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { mountAgentLoopTestDependencies } from '@deepseek-ai/dsh-agent-loop-testkit'
import { DeepSeekAdapter, resolveAdapterOptions } from '../../reference/packages/llm/llm-deepseek/src/index.ts'
import * as Retry from '../../reference/packages/llm/llm-retry/src/index.ts'

it('records complete real AgentLoop provider retry research', async () => {
  const sourceCommit = execFileSync('git', ['-C','reference','rev-parse','HEAD'], {encoding:'utf8'}).trim()
  expect(sourceCommit).toBe('cd5ef8148158c3a752a658978873241fdf8e2bbc')
  expect(execFileSync('git', ['-C','reference','status','--porcelain'], {encoding:'utf8'}).trim()).toBe('')
  expect(process.version).toBe('v22.22.2')
  const rows = []
  for (const name of ['recover','exhaust','unauthorized','retry-after','empty','partial-eof','disabled-thinking','partial-tool','cancel-backoff']) {
    const requests: any[] = []
    const server = createServer(async (request, response) => {
      const chunks = []
      for await (const chunk of request) chunks.push(chunk)
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      requests.push({body, authorization:request.headers.authorization})
      const status = name === 'unauthorized' ? 401 : name === 'exhaust' || name === 'retry-after' || name === 'cancel-backoff' || (name === 'recover' && requests.length === 1) ? 503 : 200
      let payload = status === 200 ? 'data: {"choices":[{"delta":{"content":"recovered"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n' : JSON.stringify({error:{message:'fixture failure'}})
      if (name === 'empty' && requests.length === 1) payload = 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
      if (name === 'partial-eof') payload = 'data: {"choices":[{"delta":{"content":"discarded"},"finish_reason":null}]}\n\n'
      if (name === 'partial-tool' && requests.length <= 2) {
        const delta = {tool_calls:[{index:0,id:requests.length === 1 ? 'discarded-call':'accepted-call',type:'function',function:{name:'danger',arguments:'{}'}}]}
        payload = 'data: ' + JSON.stringify({choices:[{delta,finish_reason:'tool_calls'}]}) + '\n\n' + (requests.length === 1 ? 'data: {broken}\n\n':'data: [DONE]\n\n')
      }
      response.writeHead(status, {'Content-Type':status === 200 ? 'text/event-stream':'application/json', ...(name === 'retry-after' ? {'Retry-After':'60'}:{})})
      response.end(payload)
    })
    await new Promise<void>(resolve => server.listen(0,'127.0.0.1',resolve))
    const port = (server.address() as any).port
    const delay = name === 'cancel-backoff' ? 1000:1
    const config = {baseURL:`http://127.0.0.1:${port}`,streamIdleTimeoutMs:3000,retryPolicy:{mode:'normal' as const,maxRetries:2,backoff:{initialDelayMs:delay,maxDelayMs:Math.max(delay,10),jitterRatio:0},...(name === 'partial-tool' ? {retryableCodes:['MALFORMED_RESPONSE']}:{})}, ...(name === 'disabled-thinking' ? {thinking:'disabled' as const}:{})}
    const adapter = new DeepSeekAdapter({options:()=>resolveAdapterOptions(config),resolveApiKey:async ()=>'fixture-key',resolveUserId:()=>'fixture-user' as any,prepareExtensions:async()=>({fields:{},accept:async()=>{}})})
    const ctx = new Context()
    await mountAgentLoopTestDependencies(ctx)
    await ctx.plugin(Retry)
    await ctx.plugin(AgentLoop,{agents:[]})
    ctx.llm.registerAdapter(['deepseek-official'],adapter)
    const executed: string[] = []
    if (name === 'partial-tool') ctx.tools.register({name:'danger',description:'Observe accepted execution',parameters:{type:'object',properties:{},additionalProperties:false},
      output:{schema:{type:'object',properties:{executed:{type:'boolean'}},required:['executed'],additionalProperties:false},render:()=>[{type:'text',text:'executed'}]},
      execute:async()=>{executed.push('danger');return {executed:true}}})
    const agent = ctx.agentLoop.create(SessionId('retry-session'),{provider:'deepseek-official',model:'model', ...(name === 'disabled-thinking' ? {reasoningEffort:'high' as any}:{})})
    if (name === 'cancel-backoff') ctx.on('session/event',(session,event)=>{if(session === agent.session && event.type === 'llm/retry') agent.cancel({kind:'user'})})
    try {
      agent.followup(createUserMessage({content:[{type:'text',text:'retry request'}],source:{kind:'user'}}))
      await agent.whenIdle()
      const expectedCalls = {recover:2,exhaust:3,unauthorized:1,'retry-after':1,empty:2,'partial-eof':1,'disabled-thinking':0,'partial-tool':3,'cancel-backoff':1}
      expect(requests).toHaveLength(expectedCalls[name])
      expect(agent.session.events.at(-1)?.type).toBe('turn/end')
      expect(executed).toEqual(name === 'partial-tool' ? ['danger']:[])
      rows.push({name,requests,executed,events:agent.session.events.map(event=>({type:event.type,data:event.data})),messages:agent.session.deriveMessages()})
    } finally {
      await ctx.fiber.dispose()
      server.closeAllConnections()
      await new Promise<void>(resolve=>server.close(()=>resolve()))
    }
  }

  writeFileSync(process.env.DSH_CANONICAL_LLM_RETRY_OUTPUT!,JSON.stringify({sourceCommit,node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
