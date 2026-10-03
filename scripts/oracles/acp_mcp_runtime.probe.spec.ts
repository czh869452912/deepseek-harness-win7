import { writeFileSync } from 'node:fs'
import { expect, it } from 'vitest'
import { makeBridgeHarness } from '../../reference/packages/acp/acp/tests/harness.ts'
import { scopeOf } from '@deepseek-ai/dsh-scope'

it('observes real ACP MCP scopes, consumers and fresh resume', async () => {
  const harness = await makeBridgeHarness()
  const {ctx, client} = harness
  const declarations = [{name: 'fixture', command: process.env.ACP_MCP_PYTHON!,
    args: [process.env.ACP_MCP_PEER!], env: [{name: 'EXPLICIT_TOKEN', value: 'session-owned'}]}]
  const params = {cwd: process.cwd(), mcpServers: declarations}
  const observations: any = {}
  const names = (sessionId?: string) => ctx.tools.schemas(sessionId === undefined ? undefined : scopeOf(ctx.agents.get(sessionId as any)!.ctx)).map(tool => tool.name)
  const echo = async (sessionId: string, text: string) => ctx.tools.execute({
    callId: 'owned-echo' as any, name: 'mcp__fixture__echo', arguments: {text},
    agent: ctx.agents.get(sessionId as any), signal: new AbortController().signal})
  try {
    const initialized = await client.initialize({protocolVersion: 1, clientCapabilities: {}})
    observations.mcpCapabilities = initialized.agentCapabilities?.mcpCapabilities
    const first = await client.newSession(params)
    observations.globalTools = names()
    observations.firstTools = names(first.sessionId)
    observations.firstResult = await echo(first.sessionId, 'first owned')
    const second = await client.newSession(params)
    await client.closeSession({sessionId: first.sessionId})
    observations.siblingResult = await echo(second.sessionId, 'sibling remains')
    await client.resumeSession({...params, sessionId: first.sessionId})
    observations.resumedResult = await echo(first.sessionId, 'fresh resume')
    await client.closeSession({sessionId: first.sessionId})
    await client.resumeSession({cwd: params.cwd, sessionId: first.sessionId, mcpServers: []})
    observations.emptyResumeTools = names(first.sessionId)
    await client.closeSession({sessionId: first.sessionId})
    await client.closeSession({sessionId: second.sessionId})
    observations.finalTools = names()
    observations.finalAgents = ctx.agents.list().length
    expect(observations.finalAgents).toBe(0)
  } finally {await harness.dispose()}
  writeFileSync(process.env.ACP_MCP_RUNTIME_OUTPUT!, JSON.stringify(observations, null, 2) + '\n')
}, 30000)
