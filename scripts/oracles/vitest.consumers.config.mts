import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.core.config.mts'
import ts from './official/node_modules/typescript/lib/typescript.js'
import { fileURLToPath } from 'node:url'
import { readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
const root = fileURLToPath(new URL('../../', import.meta.url))
const inventory = JSON.parse(readFileSync(join(root, 'migration/modules.json'), 'utf8'))
const aliases: { find: RegExp; replacement: string }[] = []
function alias(name: string, path: string) {
  aliases.push({ find: new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$'), replacement: path })
}
for (const row of inventory.manifests) {
  if (row.path.includes('/fixtures/')) continue
  const path = join(root, row.path), directory = dirname(path)
  const manifest = JSON.parse(readFileSync(path, 'utf8'))
  if (!manifest.name) continue
  for (const [entry, target] of Object.entries(manifest.exports || { '.': './lib/index.js' })) {
    const value = typeof target === 'string' ? target : (target as any)?.default
    if (typeof value !== 'string' || entry.includes('*')) continue
    let source = join(directory, value.replace('./lib/', './src/').replace(/\.js$/, '.ts'))
    if (!existsSync(source)) source = join(directory, value.replace('./lib/types/', './src/').replace(/\.js$/, '.ts'))
    if (existsSync(source)) alias(manifest.name + (entry === '.' ? '' : entry.slice(1)), source)
  }
  alias(manifest.name + '/package.json', path)
}
for (const [name, path] of Object.entries(base.resolve!.alias!)) alias(name, path as string)
alias('js-yaml', join(root, 'scripts/oracles/node_modules/js-yaml/index.js'))
alias('resolve.exports', join(root, 'scripts/oracles/official/node_modules/resolve.exports/dist/index.mjs'))
alias('zod', join(root, 'scripts/oracles/official/node_modules/zod/index.js'))
export default defineConfig({
  ...base,
  // Same standard-decorator transform as pinned reference/vitest.shared.ts;
  // only the development TypeScript import location differs.
  plugins: [{ name: 'pinned-standard-decorators', enforce: 'pre', transform(code, id) {
    const file = id.split('?')[0]
    if (!/\.[cm]?tsx?$/.test(file) || !/^\s*@[A-Za-z_$][\w$]*/m.test(code)) return
    const result = ts.transpileModule(code, { fileName: file, compilerOptions: {
      target: ts.ScriptTarget.ES2024, module: ts.ModuleKind.ESNext,
      jsx: file.endsWith('x') ? ts.JsxEmit.ReactJSX : undefined, sourceMap: true,
    } })
    return { code: result.outputText.replace(/\n?\/\/# sourceMappingURL=.*$/u, '\n'), map: result.sourceMapText }
  } }], resolve: { alias: aliases },
  test: { ...base.test, include: [...base.test!.include!,
    'reference/apps/cli/tests/profile-hmr.spec.ts',
    'reference/packages/preset/agent-presets/tests/mount.spec.ts',
    'reference/packages/preset/agent-presets/tests/invariant.spec.ts',
  ] },
})
