/** Private carrier: validation and search execute unchanged pinned Source code. */
import { MarketIndexError, parseMarketIndex, marketInstallTarget } from '@market/index'
import { MarketSearch } from '@market/search'
import { normalizeIndexUrl } from '@market/index-url'
import { repositoryOf, manifestRepository } from '@market/repository'
import { jsonSyntaxMessage } from './json-diagnostics'

/** One document owns its unchanged, lazily built Source search engine. */
export function openSearch(value: unknown, url: string) {
  const search = new MarketSearch(parseMarketIndex(value, url))
  return async (selection: any) => (await search.select(selection)).map(plugin => plugin.name)
}

export async function observe(operation: any): Promise<any> {
  try {
    if (operation.kind === 'repository') return { ok: true, value: repositoryOf(operation.value) ?? null }
    if (operation.kind === 'manifest-repository') return { ok: true, value: manifestRepository(operation.value) ?? null }
    if (operation.kind === 'body') {
      let value: unknown
      try { value = JSON.parse(operation.text) }
      catch (error: any) {
        const reason = `must be JSON: ${jsonSyntaxMessage(operation.text) ?? error.message}`
        return { ok: false, path: '$', reason, message: reason }
      }
      try { return { ok: true, index: parseMarketIndex(value, operation.url) } }
      catch (error: any) {
        if (!(error instanceof MarketIndexError)) throw error
        return { ok: false, path: error.path, reason: error.reason, message: error.message }
      }
    }
    if (operation.kind === 'url') {
      return { ok: true, canonical: URL.canParse(operation.text) ? new URL(operation.text).href : operation.text,
        value: normalizeIndexUrl(operation.text) }
    }
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
      ...error.code === undefined ? {} : { code: error.code, details: error.details },
      ...operation.kind !== 'url' ? {} : { canonical: URL.canParse(operation.text) ? new URL(operation.text).href : operation.text },
      ...error.path === undefined ? {} : { path: error.path, reason: error.reason } } }
  }
}
