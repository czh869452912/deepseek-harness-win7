/** Rebuild the private pure Config projector for the shipped Win7 QuickJS worker. */
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { resolve, relative, dirname, basename } from 'node:path'
const target = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
if (process.argv.length !== 4) throw new Error('usage: node scripts/build_config_projection.mjs <Source> <new-output>')
const source = resolve(process.argv[2]), output = resolve(process.argv[3]), root = process.cwd()
if (existsSync(output)) throw new Error('output must be new')
if (execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== target
  || execFileSync('git', ['-C', source, 'status', '--porcelain', '--untracked-files=no'], { encoding: 'utf8' }).trim()) {
  throw new Error('Config build requires unchanged fixed Source')
}
const require = createRequire(resolve('scripts/oracles/package.json'))
const { build } = require('esbuild')
const result = await build({
  entryPoints: ['scripts/native/config-projection/entry.ts'], bundle: true, platform: 'neutral', format: 'iife',
  globalName: '__configProjection', target: 'es2022', write: false, metafile: true, legalComments: 'external',
  outfile: resolve(output, 'projector.js'),
  alias: { '@projection/projector': resolve(source, 'packages/boot/app-boot/src/config-schema/projector.ts') },
})
const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const inputs = {}
for (const path of Object.keys(result.metafile.inputs).sort()) {
  const absolute = resolve(path)
  if (!absolute.startsWith(source + '\\') && !absolute.startsWith(source + '/')
    && !absolute.startsWith(resolve('scripts/native/config-projection') + '\\')
    && !absolute.startsWith(resolve('scripts/native/config-projection') + '/')) throw new Error('unowned bundle input: ' + path)
  inputs[relative(root, absolute).replaceAll('\\', '/')] = digest(readFileSync(absolute))
}
mkdirSync(output, { recursive: true })
const resources = {}
for (const file of result.outputFiles) {
  const name = file.path.endsWith('.LEGAL.txt') ? 'projector.LEGAL.txt' : 'projector.js'
  writeFileSync(resolve(output, name), file.contents); resources[name] = digest(file.contents)
}
for (const [name, path] of [['driver.js', 'scripts/native/config-projection/driver.js'], ['SOURCE-LICENSE', resolve(source, 'LICENSE')]]) {
  const bytes = readFileSync(path); writeFileSync(resolve(output, name), bytes); resources[name] = digest(bytes)
  inputs[relative(root, resolve(path)).replaceAll('\\', '/')] = digest(bytes)
}
const esbuildPath = require.resolve('esbuild/package.json')
for (const path of [esbuildPath, require.resolve('esbuild'), resolve('scripts/oracles/node_modules/@esbuild/win32-x64/esbuild.exe'), 'scripts/build_config_projection.mjs']) {
  inputs[relative(root, resolve(path)).replaceAll('\\', '/')] = digest(readFileSync(path))
}
const dependencies = new Set()
for (const path of Object.keys(result.metafile.inputs)) {
  if (!path.includes('node_modules')) continue
  let directory = dirname(resolve(path))
  while (!existsSync(resolve(directory, 'package.json'))) directory = dirname(directory)
  dependencies.add(directory)
}
for (const directory of dependencies) {
  const pkg = JSON.parse(readFileSync(resolve(directory, 'package.json'), 'utf8'))
  inputs[relative(root, resolve(directory, 'package.json')).replaceAll('\\', '/')] = digest(readFileSync(resolve(directory, 'package.json')))
  const licenses = readdirSync(directory).filter(name => /^(license|licence|notice)(\.|$)/i.test(name))
  if (!licenses.length) throw new Error('missing bundled dependency license: ' + pkg.name)
  for (const license of licenses) {
    const name = pkg.name.replaceAll('/', '+') + '-' + basename(license), bytes = readFileSync(resolve(directory, license))
    writeFileSync(resolve(output, name), bytes); resources[name] = digest(bytes)
    inputs[relative(root, resolve(directory, license)).replaceAll('\\', '/')] = digest(bytes)
  }
}
writeFileSync(resolve(output, 'manifest.json'), JSON.stringify({ format: 'dsh-config-projection@1', target_upstream: target,
  engine: 'shipped Win7 QuickJS', node: process.version, esbuild: JSON.parse(readFileSync(esbuildPath, 'utf8')).version,
  build_inputs: inputs, resources }, null, 2) + '\n')
console.log(JSON.stringify({ output, resources }))
