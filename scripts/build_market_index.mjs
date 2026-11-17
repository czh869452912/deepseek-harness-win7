/** Rebuild the private market validator/search artifact for the Win7 worker. */
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { resolve, relative, dirname } from 'node:path'
const target = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
if (process.argv.length !== 4) throw Error('usage: node scripts/build_market_index.mjs <Source> <new-output>')
const source = resolve(process.argv[2]), output = resolve(process.argv[3]), root = process.cwd()
if (existsSync(output)) throw Error('output must be new')
if (execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== target
  || execFileSync('git', ['-C', source, 'status', '--porcelain', '--untracked-files=no'], { encoding: 'utf8' }).trim()) {
  throw Error('Market build requires unchanged fixed Source')
}
const require = createRequire(resolve('scripts/oracles/package.json'))
const { build } = require('esbuild')
const result = await build({ entryPoints: ['scripts/native/market-index/entry.ts'], bundle: true,
  platform: 'neutral', format: 'iife', globalName: '__marketIndex', target: 'es2022', write: false,
  metafile: true, legalComments: 'external', outfile: resolve(output, 'market.js'),
  alias: {
    '@market/index': resolve(source, 'packages/util/plugin-market-index/src/index.ts'),
    '@market/search': resolve(source, 'packages/boot/plugin-market/src/search.ts'),
    '@market/index-url': resolve(source, 'packages/boot/plugin-market/src/index-url.ts'),
    '@deepseek-ai/dsh-typert-protocol': resolve(source, 'packages/typert/protocol/src/remote-error.ts'),
    '@deepseek-ai/dsh-util-values': resolve(source, 'packages/util/values/src/index.ts'),
    '@market/posix': resolve('scripts/native/market-index/posix.ts'),
    'hosted-git-info': resolve(source, 'packages/boot/plugin-market/node_modules/hosted-git-info/lib/index.js'),
    'url': resolve('scripts/native/market-index/url.ts'),
  }, plugins: [{ name: 'pure-market-repository-projection', setup(build) {
    build.onResolve({ filter: /^@market\/repository$/ }, () => ({ path: 'detail.ts', namespace: 'market-repository' }))
    build.onLoad({ filter: /.*/, namespace: 'market-repository' }, () => {
      const path = resolve(source, 'packages/boot/plugin-market/src/detail.ts'), text = readFileSync(path, 'utf8')
      const start = text.indexOf('export function repositoryOf('), end = text.indexOf('/** A read document and the files its images resolve against. */')
      if (start < 0 || end <= start || !text.slice(start, end).includes('function normalizedDirectory(')) throw Error('repository projection markers differ')
      return { contents: "import hostedGitInfo from 'hosted-git-info';\nimport { posix } from '@market/posix';\n" + text.slice(start, end),
        loader: 'ts', resolveDir: dirname(path) }
    })
  } }] })
const digest = bytes => createHash('sha256').update(bytes).digest('hex'), inputs = {}, resources = {}
const track = path => { inputs[relative(root, resolve(path)).replaceAll('\\', '/')] = digest(readFileSync(path)) }
for (const path of Object.keys(result.metafile.inputs)) {
  if (path === 'market-repository:detail.ts') continue
  const absolute = resolve(path)
  if (!absolute.startsWith(source + '\\') && !absolute.startsWith(source + '/')
    && !absolute.startsWith(resolve('scripts/native/market-index') + '\\')
    && !absolute.startsWith(resolve('scripts/native/market-index') + '/')) throw Error('unowned input: ' + path)
  track(path)
}
track(resolve(source, 'packages/boot/plugin-market/src/detail.ts'))
mkdirSync(output, { recursive: true })
const copy = (name, path) => {
  const bytes = readFileSync(path); writeFileSync(resolve(output, name), bytes)
  resources[name] = digest(bytes); track(path)
}
for (const file of result.outputFiles) {
  const name = file.path.endsWith('.LEGAL.txt') ? 'market.LEGAL.txt' : 'market.js'
  writeFileSync(resolve(output, name), file.contents); resources[name] = digest(file.contents)
}
for (const [name, path] of [ ['driver.js', 'scripts/native/market-index/driver.js'], ['search-driver.js', 'scripts/native/market-index/search-driver.js'],
  ['SOURCE-LICENSE', resolve(source, 'LICENSE')], ['url.js', 'dsh/host/browser_compat/url.js'],
  ['url.LICENSE.txt', 'dsh/host/browser_compat/url.LICENSE.txt'], ['url-input.json', 'dsh/host/browser_compat/url-input.json'] ]) copy(name, path)
const dependencies = new Set()
for (const path of Object.keys(result.metafile.inputs)) {
  if (!path.includes('node_modules')) continue
  let directory = dirname(resolve(path))
  while (!existsSync(resolve(directory, 'package.json')) || !JSON.parse(readFileSync(resolve(directory, 'package.json'), 'utf8')).name) directory = dirname(directory)
  dependencies.add(directory)
}
for (const directory of dependencies) {
  const pkg = JSON.parse(readFileSync(resolve(directory, 'package.json'), 'utf8')); track(resolve(directory, 'package.json'))
  const licenses = readdirSync(directory).filter(name => /^(license|licence|notice)(\.|$)/i.test(name))
  if (!licenses.length) throw Error('missing license: ' + pkg.name)
  for (const license of licenses) copy(pkg.name.replaceAll('/', '+') + '-' + license, resolve(directory, license))
}
for (const path of [require.resolve('esbuild/package.json'), require.resolve('esbuild'),
  resolve('scripts/oracles/node_modules/@esbuild/win32-x64/esbuild.exe'), 'scripts/build_market_index.mjs']) track(path)
writeFileSync(resolve(output, 'manifest.json'), JSON.stringify({ format: 'dsh-market-index@1', target_upstream: target,
  engine: 'shipped Win7 QuickJS', node: process.version, esbuild: require('esbuild').version,
  scheduling: 'MiniSearch chunk timer callbacks queued as microtasks in isolated worker; no external I/O',
  repository_projection: 'Unchanged repositoryOf, manifestRepository and normalizedDirectory function slice from pinned detail.ts; private path.posix subset and WHATWG URL carrier',
  build_inputs: inputs, resources }, null, 2) + '\n')
console.log(JSON.stringify({ output, resources }))
