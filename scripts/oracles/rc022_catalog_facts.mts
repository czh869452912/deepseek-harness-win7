/** Real-file observations from the unchanged pinned prerequisite reader. */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const [source, corpus, workspace] = process.argv.slice(2)
const base = resolve(source!, 'packages/session/session-persistence-jsonl/src')
const { prepareCatalogFacts } = await import(pathToFileURL(join(base, 'catalog-migration.ts')).href)
const { compressZstdFrame } = await import(pathToFileURL(join(base, 'zstd.ts')).href)
const { generationLogFilename } = await import(pathToFileURL(join(base, 'format.ts')).href)
const cases = JSON.parse(await readFile(corpus!, 'utf8'))
const results: any[] = []
for (const row of cases) {
  const root = resolve(workspace!, row.case)
  await mkdir(root, { recursive: true })
  const header = { version: 3, id: 'child', createdAt: 2, isSeeded: false,
    delegationDepth: 1, origin: 'subagent', parentSession: 'parent', ...row.header }
  const physical: any = { type: 'session', ...header }
  if (header.version < 2) { delete physical.isSeeded; if (header.isSeeded) physical.seedLength = 0 }
  const filename = row.filename ?? generationLogFilename(header.version, row.compression)
  const path = join(root, filename)
  const first = row.headerText ?? JSON.stringify(physical) + '\n'
  const body = row.bodyText ?? row.events.map((event: any) => JSON.stringify(event) + '\n').join('')
  await writeFile(path, row.compression === 'none' ? first + body : Buffer.concat([
    await compressZstdFrame(first), ...(body ? [await compressZstdFrame(body)] : [])]))
  const original = await readFile(path)
  const controller = new AbortController()
  if (row.abort) controller.abort(new Error('cancelled prerequisite'))
  const result: any = { case: row.case }
  const errorValue = (error: any) => ({ name: error.name, message: error.message })
  try {
    const prepared = await prepareCatalogFacts('parent', [{ path, header: { ...header, ...row.indexHeader } }], row.compression, controller.signal)
    result.facts = prepared.facts
    result.failures = prepared.failures.map((item: any) => ({ path: item.path, error: errorValue(item.error) }))
    result.unchanged = original.equals(await readFile(path))
    await prepared.validate()
    result.stable = true
    if (row.mutate) {
      await writeFile(path, Buffer.concat([original, Buffer.from('changed')]))
      try { await prepared.validate(); result.changed = false }
      catch (error) { result.changed = errorValue(error) }
    }
  } catch (error) { result.error = errorValue(error) }
  results.push(JSON.parse(JSON.stringify(result).split(root.replaceAll('\\', '\\\\')).join('<fixture>')))
}
process.stdout.write(JSON.stringify(results))
