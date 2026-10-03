import { expect, it } from 'vitest'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { makeBridgeHarness } from '../../reference/packages/acp/acp/tests/harness.ts'

const cwd = process.cwd()
const modes = ['empty', 'pagination', 'filter', 'cursors', 'resume-refusals', 'reservation', 'shared-close', 'close-failure']

function header(id: string, createdAt = 10, directory = cwd, extra = {}) {
  return { version: 0, id, createdAt, cwd: directory, ...extra }
}

it('observes bounded ACP persisted Session lifecycle fields from the original handlers', async () => {
  const observations: unknown[] = []
  for (const mode of modes) {
    const harness = await makeBridgeHarness({ config: { sessionListPageSize: mode === 'pagination' ? 2 : 100 } })
    const { ctx, client } = harness
    try {
      if (mode === 'empty') {
        const created = await client.newSession({ cwd, mcpServers: [] })
        const materialized = (await ctx.sessionPersistence.list()).some(row => row.id === created.sessionId)
        const hidden = await client.listSessions({})
        const closed = await client.closeSession({ sessionId: created.sessionId })
        const listed = await client.listSessions({})
        await client.resumeSession({ sessionId: created.sessionId, cwd })
        observations.push({ mode, materialized, hidden, closed,
          listedIdentity: listed.sessions.length === 1 && listed.sessions[0]?.sessionId === created.sessionId,
          listedCwd: listed.sessions[0]?.cwd, hiddenAfterResume: await client.listSessions({}) })
      }
      if (mode === 'pagination') {
        const rows = [header('😀'), header('old', 9), header('β'), header('Z'), header('a'), header('new', 12)]
        ctx.sessionPersistence.list = async () => rows as any
        const pages = []
        let cursor: string | undefined
        do {
          const page = await client.listSessions({ cursor })
          pages.push(page)
          cursor = page.nextCursor ?? undefined
        } while (cursor !== undefined)
        observations.push({ mode, pages })
      }
      if (mode === 'filter') {
        const created = await client.newSession({ cwd, mcpServers: [] })
        const directory = join(cwd, 'missing-filter')
        const rows = [header(created.sessionId, 100, directory),
          header('subagent', 99, directory, { origin: 'subagent' }),
          header('fork', 98, directory, { parentSession: 'parent' }),
          { version: 0, id: 'no-cwd', createdAt: 97 }, header('relative', 96, 'relative'),
          header('foreign', 95, directory), header('other', 94, join(cwd, 'other')),
          header('valid-b', 3, directory), header('valid-a', 3, directory)]
        ctx.sessionPersistence.list = async () => rows as any
        const get = ctx.sessions.get.bind(ctx.sessions)
        ctx.sessions.get = ((id: string) => id === 'foreign' ? {} : get(id as any)) as any
        observations.push({ mode, result: await client.listSessions({ cwd: join(directory, 'nested', '..') }) })
      }
      if (mode === 'cursors') {
        const values = ['', '*', 'A', 'bnVsbA', 'W10', 'Wy0xLCJpZCJd', 'WzEsIiJd', 'W3RydWUsImlkIl0', 'WzEsImlkIl0=', 'WyAxLCAiaWQiIF0']
        const rejected = []
        for (const cursor of values) {
          try { await client.listSessions({ cursor }); rejected.push(false) }
          catch (error) { rejected.push((error as Error).message.includes('cursor is invalid')) }
        }
        expect(rejected.every(Boolean)).toBe(true)
        observations.push({ mode, rejected })
      }
      if (mode === 'resume-refusals') {
        const created = await client.newSession({ cwd, mcpServers: [] })
        const rows = [header('subagent', 9, cwd, { origin: 'subagent' }),
          header('fork', 8, cwd, { parentSession: 'parent' }),
          { version: 0, id: 'no-cwd', createdAt: 7 }, header('wrong', 6, join(cwd, 'other'))]
        ctx.sessionPersistence.list = async () => rows as any
        let calls = 0
        ctx.agents.resume = async () => { calls++; throw new Error('unexpected factory call') }
        const cases = [['unknown', 'not resumable'], ['subagent', 'not resumable'], ['fork', 'not resumable'],
          ['no-cwd', 'cwd does not match'], ['wrong', 'cwd does not match'], [created.sessionId, 'already active']]
        const rejected = []
        for (const [sessionId, detail] of cases) {
          try { await client.resumeSession({ sessionId, cwd }); rejected.push(false) }
          catch (error) { rejected.push((error as Error).message.includes(detail!)) }
        }
        expect(rejected.every(Boolean)).toBe(true)
        observations.push({ mode, rejected, factoryCalls: calls })
      }
      if (mode === 'reservation') {
        const entered = Promise.withResolvers<void>()
        const release = Promise.withResolvers<void>()
        let first = true
        ctx.sessionPersistence.list = async () => {
          if (first) { first = false; entered.resolve(); await release.promise; return [] }
          return [header('saved')] as any
        }
        let calls = 0
        ctx.agents.resume = async () => { calls++; throw new Error('fixture factory failure') }
        const pending = client.resumeSession({ sessionId: 'saved', cwd }).catch(error => error as Error)
        await entered.promise
        const hidden = await client.listSessions({})
        const duplicate = await client.resumeSession({ sessionId: 'saved', cwd }).then(() => '', error => (error as Error).message)
        release.resolve()
        const failure = await pending
        const retry = await client.resumeSession({ sessionId: 'saved', cwd }).then(() => '', error => (error as Error).message)
        observations.push({ mode, hidden, duplicateRejected: duplicate.includes('already active'),
          firstRejected: (failure as Error).message.includes('not resumable'),
          retryReachedFactory: calls === 1, retryRejected: retry.length > 0, factoryCalls: calls })
      }
      if (mode === 'shared-close') {
        const created = await client.newSession({ cwd, mcpServers: [] })
        const agent = ctx.agents.get(created.sessionId as any)!
        const entered = Promise.withResolvers<void>()
        const release = Promise.withResolvers<void>()
        const idle = agent.whenIdle.bind(agent)
        agent.whenIdle = async () => { entered.resolve(); await release.promise; return idle() }
        const cancel = agent.cancel.bind(agent)
        let userCancels = 0
        agent.cancel = cause => { if (cause.kind === 'user') userCancels++; return cancel(cause) }
        const first = client.closeSession({ sessionId: created.sessionId })
        await entered.promise
        const second = client.closeSession({ sessionId: created.sessionId })
        const refused = await client.prompt({ sessionId: created.sessionId, prompt: [{ type: 'text', text: 'late' }] })
          .then(() => false, error => (error as Error).message.includes('session is closing'))
        release.resolve()
        observations.push({ mode, results: await Promise.all([first, second]), refused, userCancels,
          agentGone: ctx.agents.get(created.sessionId as any) === undefined })
      }
      if (mode === 'close-failure') {
        const created = await client.newSession({ cwd, mcpServers: [] })
        const agent = ctx.agents.get(created.sessionId as any)!
        const idle = agent.whenIdle.bind(agent)
        let first = true
        agent.whenIdle = async () => { if (first) { first = false; throw new Error('fixture idle failure') } return idle() }
        const detail = await client.closeSession({ sessionId: created.sessionId }).then(() => '', error => (error as Error).message)
        const listed = await client.listSessions({})
        observations.push({ mode, reported: detail.includes('session close failed') && detail.includes('fixture idle failure'),
          agentGone: ctx.agents.get(created.sessionId as any) === undefined,
          listedIdentity: listed.sessions[0]?.sessionId === created.sessionId })
      }
    } finally { await harness.dispose() }
  }
  writeFileSync(process.env.ACP_SESSION_CONTROLS_OUTPUT!, JSON.stringify(observations, null, 2), 'utf8')
})
