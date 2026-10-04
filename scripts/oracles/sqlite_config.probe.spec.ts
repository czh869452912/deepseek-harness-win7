import {writeFileSync} from 'node:fs'
import {it} from 'vitest'
import Persistence from '../../reference/packages/session/session-persistence-sqlite/src/index.ts'

it('observes original SQLite configuration defaults and refusal messages', () => {
  const cases: any[] = [{}, {path: ':memory:'}, {path: ''}, {path: null}, {path: 12},
    {path: ':memory:', journalMode: 'memory'}, {path: ':memory:', journalMode: null},
    {path: ':memory:', busyTimeoutMs: 0}, {path: ':memory:', busyTimeoutMs: 2147483647},
    {path: ':memory:', busyTimeoutMs: -1}, {path: ':memory:', busyTimeoutMs: 2147483648},
    {path: ':memory:', busyTimeoutMs: 0.5}, {path: ':memory:', busyTimeoutMs: true},
    {path: ':memory:', preparedSessionCacheSize: 0}, {path: ':memory:', preparedSessionCacheSize: 1},
    {path: ':memory:', preparedSessionCacheSize: 1.5},
    {path: ':memory:', writeBatchMaxDelayMs: 1}, {path: ':memory:', writeBatchMaxDelayMs: 2147483647},
    {path: ':memory:', writeBatchMaxDelayMs: 0}, {path: ':memory:', writeBatchMaxDelayMs: 2147483648},
    {path: ':memory:', extra: 'retained'}, {path: ':memory:', busyTimeoutMs: null}]
  const rows = cases.map((input, index) => {
    try { return {name: String(index), input, value: Persistence.Config(input)} }
    catch (error: any) { return {name: String(index), input, error: error.message} }
  })
  writeFileSync(process.env.SQLITE_CONFIG_REPORT!, JSON.stringify({node: process.version, rows}))
})
