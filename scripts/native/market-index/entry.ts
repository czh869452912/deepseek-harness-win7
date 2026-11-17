/** Private carrier: validation and search execute unchanged pinned Source code. */
import { parseMarketIndex, marketInstallTarget } from '@market/index'
import { MarketSearch } from '@market/search'

export async function observe(operation: any): Promise<any> {
  try {
    const index = parseMarketIndex(operation.value, operation.url)
    if (operation.kind === 'search') {
      const engine = new MarketSearch(index)
      const results = []
      for (const selection of operation.selections) {
        results.push((await engine.select(selection)).map(plugin => plugin.name))
      }
      return { ok: true, results }
    }
    return { ok: true, index, targets: index.plugins.map(plugin => ({
      name: plugin.name,
      versions: plugin.versions.map(version => marketInstallTarget(plugin.name, version)),
    })) }
  } catch (error: any) {
    return { ok: false, error: { name: error.name, message: error.message,
      ...error.path === undefined ? {} : { path: error.path, reason: error.reason } } }
  }
}
