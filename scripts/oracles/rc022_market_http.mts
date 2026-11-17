import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { load } from './rc022_subagent_fixture.mts'
const { Context, Service } = await load('vendor/cordis/src/index.ts')
const { default: Market } = await load('packages/boot/plugin-market/src/index.ts')
const { base, paths } = JSON.parse(readFileSync(process.argv[3], 'utf8')), rows = [], raw = []
for (const path of paths) {
  const ctx = new Context()
  class Manager extends Service { constructor(inner: any) { super(inner, 'pluginManager') } listBundles() { return [] } listVersionExemptions() { return { exemptions: {} } } }
  await ctx.plugin(Manager); await ctx.plugin(Market, { indexes: [], fetchTimeoutMs: path === 'slow' ? 50 : 2000, maxBytes: 100, detailCacheDir: '/nonexistent/plugin-market-detail-cache' })
  const market: any = ctx.pluginMarket; let result: any, timer
  if (path === 'abort') timer = setTimeout(() => market.lifetime.abort(Error('Plugin market disposed')), 20)
  try { result = { ok: true, index: await market.fetchIndex(base+path) } }
  catch (error: any) { result = { ok: false, code: error.code, message: error.message.replaceAll(base, 'BASE/'),
    details: Object.fromEntries(Object.entries(error.details).map(([key, value]) => [key, typeof value === 'string' ? value.replaceAll(base, 'BASE/') : value])) } }
  finally { clearTimeout(timer); await ctx.fiber.dispose() }
  raw.push({ path, result })
  if (path === 'empty' && !result.ok) result = { ok: false, code: result.code, path: result.details.path, reasonPrefix: result.details.reason.split(':')[0]+':' }
  rows.push({ path, result })
}
writeFileSync(resolve(dirname(process.argv[3]), 'source-diagnostics.json'), JSON.stringify(raw))
console.log(JSON.stringify(rows))
