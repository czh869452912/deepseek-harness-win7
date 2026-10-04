import { registerHooks } from 'node:module'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import ts from './official/node_modules/typescript/lib/typescript.js'

const root = fileURLToPath(new URL('../../', import.meta.url))
const aliases = new Map()
const inventory = JSON.parse(readFileSync(join(root, 'migration/modules.json'), 'utf8'))
for (const row of inventory.manifests) {
  if (row.path.includes('/fixtures/')) continue
  const manifestPath = join(root, row.path)
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  for (const [entry, target] of Object.entries(manifest.exports || { '.': './lib/index.js' })) {
    const value = typeof target === 'string' ? target : target?.default
    if (typeof value !== 'string' || entry.includes('*')) continue
    const source = join(dirname(manifestPath), value.replace('./lib/', './src/').replace(/\.js$/, '.ts'))
    if (existsSync(source)) aliases.set(manifest.name + (entry === '.' ? '' : entry.slice(1)), source)
  }
}
for (const [name, source] of Object.entries({
  '@deepseek-ai/cordis': 'reference/vendor/cordis/src/index.ts',
  '@deepseek-ai/cosmokit': 'reference/vendor/cosmokit/src/index.ts',
  '@deepseek-ai/schemastery': 'reference/vendor/schemastery/src/index.ts',
  'node-pty': 'scripts/oracles/official/node_modules/node-pty/lib/index.js',
  'koffi': 'scripts/oracles/official/node_modules/koffi/index.js',
})) aliases.set(name, join(root, source))
registerHooks({
  resolve(specifier, context, nextResolve) {
    const source = aliases.get(specifier)
    return nextResolve(source ? pathToFileURL(source).href : specifier, context)
  },
  load(url, context, nextLoad) {
    if (url.startsWith('file:') && url.endsWith('.ts')) {
      const fileName = fileURLToPath(url)
      const result = ts.transpileModule(readFileSync(fileName, 'utf8'), {fileName,
        compilerOptions: {target: ts.ScriptTarget.ES2024, module: ts.ModuleKind.ESNext}})
      return {format: 'module', source: result.outputText, shortCircuit: true}
    }
    return nextLoad(url, context)
  },
})
