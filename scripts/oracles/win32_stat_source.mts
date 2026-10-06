import {execFileSync} from 'node:child_process'
import {chmodSync, mkdirSync, statSync, utimesSync, writeFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {Context} from '@deepseek-ai/cordis'
import FsLocal from '@deepseek-ai/dsh-fs-local'

const destination = process.env.DSH_STAT_DESTINATION!
mkdirSync(destination)
for (const [name, content] of [['text.txt', 'abc'], ['empty.txt', ''], ['中文.txt', '中'], ['fixed-time.txt', 'fixed']]) {
  writeFileSync(resolve(destination, name), content, 'utf8')
}
utimesSync(resolve(destination, 'fixed-time.txt'), new Date('2020-01-02T03:04:05.123Z'), new Date('2020-01-02T03:04:05.123Z'))
mkdirSync(resolve(destination, 'directory'))
writeFileSync(resolve(destination, 'metadata-change.txt'), 'metadata', 'utf8')
await new Promise(release => setTimeout(release, 10))
chmodSync(resolve(destination, 'metadata-change.txt'), 0o444)
const ctx = new Context(), rows: any[] = []
try {
  await ctx.plugin(FsLocal, {cwd: destination})
  for (const name of ['text.txt', 'empty.txt', '中文.txt', 'fixed-time.txt', 'directory', 'metadata-change.txt', 'missing.txt']) {
    const target = await ctx.fs.resolve(name)
    const info = await ctx.fs.stat(target)
    const link = await ctx.fs.lstat(name)
    const raw = info === undefined ? null : statSync(resolve(destination, name), {bigint: true})
    rows.push({name, stat: info ?? null, lstat: link ?? null, raw: raw === null ? null : {
      dev: String(raw.dev), ino: String(raw.ino), size: String(raw.size),
      mtimeNs: String(raw.mtimeNs), ctimeNs: String(raw.ctimeNs),
    }})
  }
} finally {
  await ctx.fiber.dispose()
}
writeFileSync(process.env.DSH_STAT_SOURCE_OUTPUT!, JSON.stringify({
  sourceCommit: execFileSync('git', ['-C', process.env.DSH_STAT_SOURCE_ROOT!, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim(),
  node: process.version, destination, rows,
}, null, 2) + '\n', {encoding: 'utf8', flag: 'wx'})
