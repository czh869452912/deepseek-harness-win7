import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync, existsSync, mkdirSync, copyFileSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
process.chdir(root)
const sourceCommit = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
const buildInputs = {
  'scripts/oracles/node_modules/esbuild/lib/main.js': '61ec0ba144ff93f4bf0e96ad6fab6f430ede0aa13e27ace8063ed63ba416b3cd',
  'scripts/oracles/node_modules/@esbuild/win32-x64/esbuild.exe': 'c7bee37877d0aa6a046e52783fa0a2cf1a9ce5579d68bb3083bda99d4bff18ef',
  'scripts/oracles/node_modules/esbuild/package.json': '9d0bc453f4e791553c4cc2298ba023b409241fd9801e494741666eb0f6051490',
}
function digest(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}
if (process.version !== 'v22.22.2') throw new Error('workflow build requires pinned development Node22.22.2')
if (execFileSync('git', ['-C', 'reference', 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== sourceCommit
    || execFileSync('git', ['-C', 'reference', 'status', '--porcelain'], { encoding: 'utf8' }).trim()) {
  throw new Error('workflow build requires unchanged pinned Source')
}
for (const [path, expected] of Object.entries(buildInputs)) {
  if (digest(path) !== expected) throw new Error('workflow build input differs: ' + path)
}
if (process.argv.length !== 3) throw new Error('usage: node scripts/build_workflow.mjs <new-output-directory>')
const output = resolve(process.argv[2])
if (existsSync(output)) throw new Error('workflow build output must be new')
process.env.ESBUILD_BINARY_PATH = resolve('scripts/oracles/node_modules/@esbuild/win32-x64/esbuild.exe')
const { build } = await import('./oracles/node_modules/esbuild/lib/main.js')
const result = await build({
  entryPoints: ['scripts/native/workflow/entry.ts'], bundle: true, platform: 'neutral', format: 'iife',
  globalName: '__workflowSource', treeShaking: true, write: false, metafile: true,
  tsconfig: 'reference/tsconfig.base.json',
  alias: {
    'node:vm': resolve('scripts/native/workflow/vm.js'),
    '@deepseek-ai/dsh-llm': resolve('scripts/native/workflow/llm.ts'),
    '@deepseek-ai/dsh-session': resolve('scripts/native/workflow/session.ts'),
    '@deepseek-ai/dsh-tools': resolve('reference/packages/core/tools/src/json-schema.ts'),
  },
})
const inputs = {}
for (const path of Object.keys(result.metafile.inputs).sort()) {
  if (!path.startsWith('reference/') && !path.startsWith('scripts/native/workflow/')) {
    throw new Error('workflow bundle has an unowned input: ' + path)
  }
  if (path.startsWith('reference/')) {
    execFileSync('git', ['-C', 'reference', 'ls-files', '--error-unmatch', path.slice('reference/'.length)], { stdio: 'pipe' })
  }
  inputs[path] = digest(path)
}
for (const path of ['scripts/build_workflow.mjs', 'scripts/native/workflow/driver.js', 'reference/tsconfig.base.json']) {
  inputs[path] = digest(path)
}
mkdirSync(output)
writeFileSync(resolve(output, 'source.js'), result.outputFiles[0].contents)
copyFileSync('scripts/native/workflow/driver.js', resolve(output, 'driver.js'))
const licenses = {
  'SOURCE-LICENSE': 'reference/LICENSE',
  'CORDIS-LICENSE': 'reference/vendor/cordis/LICENSE',
  'COSMOKIT-LICENSE': 'reference/vendor/cosmokit/LICENSE',
}
for (const [name, path] of Object.entries(licenses)) {
  inputs[path] = digest(path)
  copyFileSync(path, resolve(output, name))
}
writeFileSync(resolve(output, 'build-provenance.json'), JSON.stringify({
  sourceCommit, inputs, buildInputs, node: process.version, esbuild: '0.28.2', metafile: result.metafile,
  nodeBinarySha256: digest(process.execPath),
  scope: 'Unchanged pinned workflow session/runtime/realm/schema algorithms; owned vm/port substrate. Full Node APIs and engine-specific error stacks remain unqualified.',
}, null, 2) + '\n')
const resources = {}
for (const name of ['source.js', 'driver.js', 'build-provenance.json', ...Object.keys(licenses)]) {
  resources[name] = digest(resolve(output, name))
}
writeFileSync(resolve(output, 'workflow.json'), JSON.stringify({ sourceCommit, resources }, null, 2) + '\n')
console.log(JSON.stringify({ output: relative(root, output), manifest: digest(resolve(output, 'workflow.json')), bytes: result.outputFiles[0].contents.length }))
