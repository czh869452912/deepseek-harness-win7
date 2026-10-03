import { writeFileSync } from 'node:fs'
import { expect, it, vi } from 'vitest'
import ApprovalService from '@deepseek-ai/dsh-user-approval'
import { makeBridgeHarness } from '../../reference/packages/acp/acp/tests/harness.ts'

vi.mock('node:crypto', async () => ({ ...await vi.importActual<typeof import('node:crypto')>('node:crypto'),
  randomUUID: () => '00000000-0000-4000-8000-000000000001' }))

it('observes the exact one-shot permission bridge including malformed responses', async () => {
  const rows = []
  for (const [mode, response] of [
    ['allow', { outcome: { outcome: 'selected', optionId: 'allow-once' } }],
    ['reject', { outcome: { outcome: 'selected', optionId: 'reject-once' } }],
    ['unknown-option', { outcome: { outcome: 'selected', optionId: 'allow-always' } }],
    ['cancelled', { outcome: { outcome: 'cancelled' } }],
    ['unknown-kind-allow', { outcome: { outcome: 'unknown', optionId: 'allow-once' } }],
    ['missing-kind-allow', { outcome: { optionId: 'allow-once' } }],
    ['missing-outcome', {}], ['null-response', null], ['remote-error', null],
    ['same-id-foreign', null], ['missing-call-id', null], ['pre-abort', null],
  ] as const) {
    const harness = await makeBridgeHarness()
    try {
      await harness.ctx.plugin(ApprovalService)
      const { sessionId } = await harness.client.newSession({ cwd: process.cwd(), mcpServers: [] })
      const owned = harness.ctx.agents.get(sessionId as any)!
      owned.session.append('turn/start', { turn: 1 })
      owned.session.append('step/start', { turn: 1, step: 1 })
      owned.session.append('tool/call', { turn: 1, step: 1, callId: 'call-9' as any, name: 'bash', arguments: '{}' })
      let updateBeforePermission: boolean | null = null
      harness.onPermission = () => {
        updateBeforePermission = harness.sessionUpdates.at(-1)?.update.sessionUpdate === 'tool_call'
        if (mode === 'remote-error') throw new Error('client gone')
        return response as any
      }
      const agent = mode === 'same-id-foreign' ? Object.assign(Object.create(owned), { session: owned.session }) : owned
      const outcome = await harness.ctx.approval.request({ agent, toolName: 'bash',
        ...(mode === 'missing-call-id' ? {} : { callId: 'call-9' as any }),
        ...(mode === 'pre-abort' ? { signal: AbortSignal.abort() } : {}),
      })
      await vi.waitFor(() => expect(harness.sessionUpdates).toHaveLength(1))
      const audit = agent.session.events.filter(event => event.type === 'approval/asked' || event.type === 'approval/decided')
      rows.push({ mode, response, outcome, requests: harness.permissionRequests,
        updates: harness.sessionUpdates, updateBeforePermission,
        audit: { types: audit.map(event => event.type), correlated: audit[0].data.id === audit[1].data.id,
          outcome: audit[1].data.outcome } })
    } finally { await harness.dispose() }
  }
  expect(rows).toHaveLength(12)
  writeFileSync(process.env.ACP_PERMISSIONS_OUTPUT!, JSON.stringify(rows, null, 2))
})
