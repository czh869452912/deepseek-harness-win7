/** Capture normalized definitions from the fixed upstream tool-office implementation.
 * Usage: node scripts/generate_office_tools.mjs SOURCE_ROOT OUTPUT_JSON
 * JSON intentionally omits executable callbacks; the native plugin supplies them.
 */
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
const [source, output] = process.argv.slice(2)
if (!source || !output) throw new Error('SOURCE_ROOT and OUTPUT_JSON are required')
const { apply, Config } = await import(pathToFileURL(path.resolve(source, 'packages/document/tool-office/lib/index.js')))
const definitions = []
apply({ on() {}, tools: { register(definition) { definitions.push(definition) } } }, Config({}))
fs.writeFileSync(output, JSON.stringify(definitions, null, 2) + '\n', 'utf8')
