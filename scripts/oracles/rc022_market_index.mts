import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
const source = resolve(process.argv[2])
const { parseMarketIndex, marketInstallTarget } = await import(pathToFileURL(resolve(source, 'packages/util/plugin-market-index/src/index.ts')).href)
const { MarketSearch } = await import(pathToFileURL(resolve(source, 'packages/boot/plugin-market/src/search.ts')).href)
const rows = []
for (const operation of JSON.parse(readFileSync(process.argv[3], 'utf8'))) {
  try {
    const index = parseMarketIndex(operation.value, operation.url)
    if (operation.kind === 'search') {
      const engine = new MarketSearch(index), results = []
      for (const selection of operation.selections) results.push((await engine.select(selection)).map(plugin => plugin.name))
      rows.push({ ok: true, results })
    } else rows.push({ ok: true, index, targets: index.plugins.map(plugin => ({ name: plugin.name,
      versions: plugin.versions.map(version => marketInstallTarget(plugin.name, version)) })) })
  } catch (error: any) {
    rows.push({ ok: false, error: { name: error.name, message: error.message,
      ...error.path === undefined ? {} : { path: error.path, reason: error.reason } } })
  }
}
console.log(JSON.stringify(rows))
