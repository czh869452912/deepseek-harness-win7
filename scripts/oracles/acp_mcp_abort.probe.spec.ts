import { writeFileSync } from 'node:fs'
import { readFile, writeFile } from 'node:fs/promises'
import { expect, it, vi } from 'vitest'
import { makeBridgeHarness } from '../../reference/packages/acp/acp/tests/harness.ts'
import { AcpSession } from '../../reference/packages/acp/acp/src/session.ts'

it('observes actual factory cancellation while the owned MCP initializer is blocked', async () => {
  const harness = await makeBridgeHarness()
  const controller = new AbortController()
  const marker = process.env.ACP_MCP_MARKER!
  const release = process.env.ACP_MCP_RELEASE!
  const childRecord = process.env.ACP_MCP_CHILD_RECORD!
  let settled = false
  const pending = AcpSession.create(harness.ctx, {cwd: process.cwd(), sessionId: 'unpublished-mcp' as any,
    mcpServers: [{name: 'blocked', command: process.env.ACP_MCP_PYTHON!,
      args: [process.env.ACP_MCP_PEER!, marker, release, childRecord], env: []}],
    agentOptions: {}, fallbackSelection: undefined, signal: controller.signal, notify: async () => {}})
    .then(() => ({rejected: false}), error => ({rejected: true, name: error.name, message: error.message}))
    .finally(() => {settled = true})
  try {
    await vi.waitFor(async () => expect(await readFile(marker, 'utf8')).toBe('ready'), {timeout: 5000})
    const beforeAgents = harness.ctx.agents.list().length
    controller.abort(new Error('controlled setup abort'))
    await new Promise(resolve => setTimeout(resolve, 50))
    const beforeRelease = settled
    await writeFile(release, 'release', 'utf8')
    const result = await pending
    const record = JSON.parse(await readFile(childRecord, 'utf8'))
    writeFileSync(process.env.ACP_MCP_ABORT_OUTPUT!, JSON.stringify({beforeAgents, beforeRelease, result,
      finalAgents: harness.ctx.agents.list().length, finalTools: harness.ctx.tools.schemas(),
      childClosed: record.closed, childPid: record.pid}, null, 2) + '\n')
  } finally {
    await writeFile(release, 'release', 'utf8')
    await pending
    await harness.dispose()
  }
}, 30000)
