// Development-only regeneration from the lockfile-pinned dependency; no Node runtime in the product.
import { readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { builtinProviders, getBuiltinModels, getBuiltinProviders } from './official/node_modules/@earendil-works/pi-ai/dist/providers/all.js'

const root = new URL('../../', import.meta.url)
const pkg = JSON.parse(readFileSync(new URL('./official/node_modules/@earendil-works/pi-ai/package.json', import.meta.url)))
if (pkg.version !== '0.84.2') throw new Error('catalog dependency differs from the pinned migration version')
const providers = new Map(builtinProviders().map(provider => [provider.id, provider]))
const catalog = Object.fromEntries(getBuiltinProviders().map(id => {
  const provider = providers.get(id)
  return [id, {name: provider?.name, baseUrl: provider?.baseUrl, models: provider ? getBuiltinModels(id) : []}]
}))
const result = {source: pkg.name, version: pkg.version, author: pkg.author, license: pkg.license,
  repository: pkg.repository.url,
  lockSha256: createHash('sha256').update(readFileSync(new URL('./official/package-lock.json', import.meta.url))).digest('hex'),
  providers: catalog}
writeFileSync(new URL('dsh/llm/pi_catalog.json', root), JSON.stringify(result) + '\n')
