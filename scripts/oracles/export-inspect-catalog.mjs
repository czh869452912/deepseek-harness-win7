// Development-only extraction of the pinned generated catalogs. The product reads JSON.
import { readFileSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { runInNewContext } from 'node:vm'
import { fileURLToPath } from 'node:url'
import ts from './official/node_modules/typescript/lib/typescript.js'

const root = new URL('../../', import.meta.url)
const target = JSON.parse(readFileSync(new URL('migration/baseline.json', root), 'utf8')).target_upstream
const reference = new URL('reference/', root)
const head = execFileSync('git', ['-C', fileURLToPath(reference), 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
if (head !== target) throw new Error('reference differs from target')
if (execFileSync('git', ['-C', fileURLToPath(reference), 'status', '--porcelain', '--untracked-files=no'], { encoding: 'utf8' }).trim()) throw new Error('reference has tracked changes')
const source = 'reference/packages/extensions/tool-cordis/src/api-catalog.ts'
const raw = readFileSync(new URL(source, root), 'utf8').replace(/\r\n/g, '\n')
const exports = {}
const compiled = ts.transpileModule(raw, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS } }).outputText
runInNewContext(compiled, { exports }, { timeout: 5000 })
const catalogs = Object.fromEntries(['SERVICE_API', 'EVENT_API', 'TYPE_API', 'INHERITED_CTX_API'].map(key => {
  if (!Array.isArray(exports[key])) throw new Error('missing catalog: ' + key)
  return [key, exports[key]]
}))
const result = { target_upstream: target, source, source_sha256: createHash('sha256').update(Buffer.from(raw)).digest('hex'), catalogs }
const output = new URL('dsh/extensions/inspect_catalog.json', root)
const text = JSON.stringify(result) + '\n'
if (process.argv.includes('--check')) {
  if (readFileSync(output, 'utf8').replace(/\r\n/g, '\n') !== text) throw new Error('generated Inspect catalog is stale')
} else writeFileSync(output, text, 'utf8')
console.log(Object.fromEntries(Object.entries(catalogs).map(([key, rows]) => [key, rows.length])))
