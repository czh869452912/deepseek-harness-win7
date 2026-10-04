import {readFileSync, writeFileSync} from 'node:fs'
import {it} from 'vitest'
import {decodeSessionRow, decodeEventRow, decodeStoreIdentity, rowToMeta} from '../../reference/packages/session/session-persistence-sqlite/src/schema.ts'

it('observes original metadata physical-row and store-identity validation', () => {
  const inputs = JSON.parse(readFileSync(process.env.SQLITE_SCHEMA_INPUT!, 'utf8'))
  const rows = inputs.cases.map((item: any) => {
    try {
      const value = item.category === 'metadata' ? rowToMeta(decodeSessionRow(item.value)) :
        item.category === 'event' ? decodeEventRow(item.value) : decodeStoreIdentity(item.value)
      return {name: item.name, value}
    } catch (error: any) { return {name: item.name, error: error.message} }
  })
  writeFileSync(process.env.SQLITE_SCHEMA_OUTPUT!, JSON.stringify({node: process.version, rows}))
})
