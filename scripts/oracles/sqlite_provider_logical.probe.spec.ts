import {readFileSync, writeFileSync} from 'node:fs'
import {it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import Persistence from '@deepseek-ai/dsh-session-persistence-sqlite'

it('observes original physical provider logical refusals and stored legacy upgrades', async () => {
  const cases = JSON.parse(readFileSync(process.env.SQLITE_SCHEMA_INPUT!, 'utf8')).logicalCases
  const rows: any[] = []
  for (const item of cases) {
    const context = new Context()
    await context.plugin(SessionStore)
    const fiber = await context.plugin(Persistence, {path: ':memory:'})
    const persistence: any = context.sessionPersistence
    try {
      if (!item.missing) {
        const meta = {id: item.name, version: item.version, createdAt: 1}
        await persistence.store.materializeHeader(meta)
        if (item.events.length) await persistence.store.appendBatch(meta, item.events, true)
      }
      try {
        const loaded = await persistence.readFrom(item.name, item.sequence)
        rows.push({name: 'logical-' + item.name, value: loaded.events})
      } catch (error: any) {
        rows.push({name: 'logical-' + item.name, error: {name: error.name, message: error.message}})
      }
    } finally { await fiber.dispose() }
  }
  writeFileSync(process.env.SQLITE_LOGICAL_OUTPUT!, JSON.stringify({node: process.version, rows}))
})
