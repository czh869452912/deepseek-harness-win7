import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import JsonlSessionPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import fixtures from './session-recovery-fixtures.json'
it('observes real JSONL cold recovery without changing reference source', async () => {
  const rows = []
  for (const fixture of fixtures) {
    const root = await mkdtemp(join(tmpdir(), 'dsh-recovery-'))
    const ctx = new Context()
    try {
      await ctx.plugin(SessionStore)
      await ctx.plugin(JsonlSessionPersistence, { root, compression: 'none' })
      const p = ctx.sessionPersistence
      const meta = { id: fixture.mode, version: 0, createdAt: 1, delegationDepth: 0 }
      const path = p.locate(meta as any)!.path
      await mkdir(dirname(path), { recursive: true })
      const bytes = [JSON.stringify({ type: 'session', ...meta }), ...fixture.events.map(e => JSON.stringify(e))].join('\n') + '\n' + fixture.tail
      await writeFile(path, bytes)
      const inspected = await p.inspect(meta.id as any)
      const before = await p.readFrom(meta.id as any, 1)
      const untouched = await readFile(path, 'utf8') === bytes
      const loaded = await p.load(meta.id as any)
      const again = await p.load(meta.id as any)
      const after = await p.readFrom(meta.id as any, 0)
      rows.push({ mode: fixture.mode, inspected: inspected.events, before: before.events, untouched,
        loaded: loaded.events, again: again.events, after: after.events })
    } finally { await ctx.fiber.dispose(); await rm(root, { recursive: true, force: true }) }
  }
  await writeFile(process.env.SESSION_ORACLE_OUTPUT!, JSON.stringify(rows, null, 2))
})

