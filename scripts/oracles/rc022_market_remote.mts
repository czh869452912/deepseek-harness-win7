import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { load } from './rc022_subagent_fixture.mts'
const { Context, Service } = await load('vendor/cordis/src/index.ts')
const { default: Market } = await load('packages/boot/plugin-market/src/index.ts')
const { parseMarketIndex } = await load('packages/util/plugin-market-index/src/index.ts')
const data = JSON.parse(readFileSync(process.argv[3], 'utf8')), URL = 'https://market.example/index.json'
const ctx = new Context(), routes = new Map(), calls = [], rows = [], saved = globalThis.fetch
class Manager extends Service {
  constructor(scope: any) { super(scope, 'pluginManager') }
  listBundles() { return Promise.resolve([]) }
  listVersionExemptions() { return { exemptions: {} } }
}
class Connection extends Service {
  constructor(scope: any) { super(scope, 'connection') }
  fetch = { register(route: any) { routes.set(route.path, route); return () => routes.delete(route.path) } }
}
await ctx.plugin(Manager); await ctx.plugin(Connection)
globalThis.fetch = (async (url: string) => {
  calls.push(url); const value = data.routes[url]
  return value === undefined ? new Response('missing', { status: 404 }) :
    new Response(Array.isArray(value) ? Uint8Array.from(value) : typeof value === 'string' ? value : JSON.stringify(value))
}) as any
try {
  await ctx.plugin(Market, { indexes: [URL], detailCacheDir: join(data.directory, 'source-cache') })
  const market: any = ctx.pluginMarket
  market.repositories.isPublic = async () => true
  market.fetchIndex = async () => parseMarketIndex(data.index, URL)
  async function step(name: string, language='en', options?: any, version='1.0.0', target=URL) {
    try {
      const value = await market.readEntryDetail(target, name, version, language, options)
      rows.push({ step: name, value, fetches: calls.length }); return value
    } catch (error: any) { rows.push({ step: name, error: { code: error.code ?? null, message: error.message, details: error.details ?? null }, fetches: calls.length }) }
  }
  const first = await step('git', 'zh-CN')
  await step('git', 'zh-CN'); await step('git', 'zh-CN', { refresh: true })
  for (const name of ['npm', 'private', 'manifest', 'none', 'self', 'bad', 'missing']) await step(name)
  await step('npm', 'en', undefined, '9.0.0'); await step('npm', '../en', undefined, '1.0.0', 'https://unknown.example/')
  for (const suffix of ['?document='+first.document+'&path=img/a.png', '?document='+first.document+'&path=../escape.png',
    '?document=missing&path=a.png', '?document=x']) {
    const response = await routes.get('/api/plugin-market/detail-file').fetch(new Request('https://app.example/api/plugin-market/detail-file'+suffix))
    rows.push({ step: 'image', status: response.status, headers: Object.fromEntries(response.headers), body: [...new Uint8Array(await response.arrayBuffer())] })
  }
  rows.push({ step: 'route', paths: [...routes.keys()], calls })
} finally { await ctx.fiber.dispose(); globalThis.fetch = saved }
rows.push({ step: 'disposed', paths: [...routes.keys()] })
console.log(JSON.stringify(rows))
