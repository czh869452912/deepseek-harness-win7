import { readFileSync } from 'node:fs'
import { load } from './rc022_subagent_fixture.mts'
const { Context, Service } = await load('vendor/cordis/src/index.ts')
const { updateVolatile } = await load('vendor/cosmokit/src/index.ts')
const { default: Market } = await load('packages/boot/plugin-market/src/index.ts')
const { parseMarketIndex } = await load('packages/util/plugin-market-index/src/index.ts')
const data = JSON.parse(readFileSync(process.argv[3], 'utf8')), URL_A = 'https://market.example/index.json'
const index = parseMarketIndex(data.value, URL_A), ctx = new Context(), rows: any[] = [], calls: any[] = [], managerReads: any[] = [], writes: any[] = []
let config: any
class Manager extends Service { constructor(inner: any) { super(inner, 'pluginManager') } listBundles() { managerReads.push(1); return data.bundles } listVersionExemptions() { return { exemptions: data.exemptions } } }
class Settings extends Service { constructor(inner: any) { super(inner, 'settings') } async update(id: any, patch: any) { writes.push({ id, patch }) } }
class Capture extends Market { constructor(inner: any, resolved: any) { Object.defineProperty(inner.fiber, 'entry', { value: { options: { id: 'market' } } }); super(inner, resolved); config = resolved } }
await ctx.plugin(Manager); await ctx.plugin(Settings); await ctx.plugin(Capture, { indexes: [URL_A], detailCacheDir: '/nonexistent/plugin-market-detail-cache' })
const market: any = ctx.pluginMarket, saved = Date.now; Date.now = () => 1000
market.fetchIndex = async (url: string) => { calls.push(url); return index }
const query = async (step: string, request = { sort: { kind: 'index' }, offset: 0, limit: 100 }, target = URL_A) => {
  try { rows.push({ step, value: await market.search(target, request) }) }
  catch (error: any) { rows.push({ step, error: { code: error.code ?? null, message: error.message, details: error.details ?? null } }) }
}
try {
  await query('listing'); await query('page', { sort: { kind: 'index' }, offset: 2, limit: 3 })
  await query('text', { text: 'preview', sort: { kind: 'relevance' }, offset: 0, limit: 1 } as any)
  await query('empty-page', { sort: { kind: 'index' }, offset: 100, limit: 1 })
  rows.push({ step: 'single', value: await market.entry(URL_A, 'exempted') })
  rows.push({ step: 'unlisted', value: await market.entry(URL_A, 'unlisted') ?? null })
  data.bundles[0].version = '0.9.0'; await query('live-installation', { text: 'same', sort: { kind: 'relevance' }, offset: 0, limit: 100 } as any)
  for (const [key, values] of [['offset', [-1, 1.5, 9007199254740992, true]], ['limit', [0, 101, 1.5, true]]] as const) {
    for (const value of values) await query('invalid-'+key, { sort: { kind: 'index' }, offset: 0, limit: 1, [key]: value } as any, 'https://unconfigured.example/')
  }
  await query('unknown-index', undefined, 'https://unconfigured.example/')
  await market.setIndexes([URL_A, ' https://other.example:443/a ']); rows.push({ step: 'settings', writes, indexes: market.listIndexes() })
  const changed: number[] = []; ctx.on('plugin-market/changed', () => changed.push(1))
  updateVolatile(config.indexes, Market.Config({ indexes: [] }).indexes); ctx.emit('loader/volatile-update', [['indexes']])
  rows.push({ step: 'removed', indexes: market.listIndexes(), changed: changed.length, fetches: calls.length, managerReads: managerReads.length })
} finally { Date.now = saved; await ctx.fiber.dispose() }
console.log(JSON.stringify(rows))
