/** Build the fixed upstream Desktop shortcut owner for Electron 22. */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { join, resolve } from 'node:path'

const [, , input, esbuild, check] = process.argv
assert.ok(input && esbuild, 'Explicit Source and esbuild paths required')
const root = resolve(import.meta.dirname, '..')
const source = resolve(input)
const baseline = JSON.parse(await readFile(join(root, 'migration/baseline.json'), 'utf8'))
assert.equal(execFileSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(), baseline.target_upstream)
assert.equal(execFileSync('git', ['-C', source, 'status', '--porcelain'], { encoding: 'utf8' }).trim(), '')
const builder = createRequire(import.meta.url)(resolve(esbuild))
assert.equal(builder.version, '0.25.12')
const directory = join(source, 'apps/desktop/src')
let keyboard = await readFile(join(directory, 'keyboard.ts'), 'utf8')
function adapt(before, after) {
  assert.equal(keyboard.split(before).length, 2)
  keyboard = keyboard.replace(before, after)
}
// Electron 22 supplies positional navigation arguments and no focusedFrame accessor.
adapt('const navigation = (event: Electron.Event<Electron.WebContentsDidStartNavigationEventParams>): void => {\n      if (event.isMainFrame && !event.isSameDocument) clear()',
  'const navigation = (_event: Electron.Event, _url: string, inPlace: boolean, isMainFrame: boolean): void => {\n      if (isMainFrame && !inPlace) clear()')
adapt('const frame = contents.focusedFrame', 'const frame = contents.focusedFrame ?? contents.mainFrame')
const builds = await builder.build({
  stdin: { contents: keyboard, resolveDir: directory, sourcefile: 'keyboard.ts', loader: 'ts' },
  format: 'cjs', target: 'node16.17', platform: 'node', bundle: true, write: false,
  external: ['electron'], legalComments: 'inline',
  alias: {
    '@deepseek-ai/dsh-client-shortcuts/protocol': join(source, 'packages/client/shortcuts/src/protocol.ts'),
    '@deepseek-ai/dsh-atomic-write': join(source, 'packages/util/atomic-write/src/index.ts'),
  },
  plugins: [{
    name: 'electron22-uuid',
    setup(build) {
      build.onResolve({ filter: /^@deepseek-ai\/dsh-util-crypto$/ }, () => ({ path: 'node:crypto', external: true }))
    },
  }],
  banner: { js: '/* Generated from DeepSeek Harness ' + baseline.target_upstream + ' by scripts/build_desktop_shortcuts.mjs. */' },
})
const output = join(root, 'apps/desktop/shortcuts.cjs')
const bytes = Buffer.from(builds.outputFiles[0].contents)
if (check === '--check') assert.deepEqual(await readFile(output), bytes)
else await writeFile(output, bytes)
