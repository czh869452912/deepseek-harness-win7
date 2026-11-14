/** Observe the unchanged fixed Source helpers; no copied implementation. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const [source, corpus] = process.argv.slice(2)
const base = resolve(source!, 'packages/session/session-format-v3-to-v4/src')
const modules = await Promise.all(['tool-role', 'sources', 'content', 'developer', 'system-message',
  'message-sources', 'retired-syntax'].map(name => import(pathToFileURL(resolve(base, name + '.ts')).href)))
const functions = Object.assign({}, ...modules)
const rows = JSON.parse(readFileSync(corpus!, 'utf8'))
const result = rows.map((row: any) => {
  const before = JSON.stringify(row.args)
  try {
    const value = functions[row.operation](...row.args)
    return { case: row.case, ok: true, value: value ?? null,
      same: value === row.args[0], unchanged: before === JSON.stringify(row.args),
      serialized: JSON.stringify(value ?? null) }
  } catch (error: any) {
    return { case: row.case, ok: false, name: error.name, message: error.message,
      unchanged: before === JSON.stringify(row.args) }
  }
})
process.stdout.write(JSON.stringify(result))
