import { load } from './rc022_subagent_fixture.mts'
const { Context, Service } = await load('vendor/cordis/src/index.ts')
const { updateVolatile } = await load('vendor/cosmokit/src/index.ts')
const { default: Market } = await load('packages/boot/plugin-market/src/index.ts')
const { normalizeIndexUrl } = await load('packages/boot/plugin-market/src/index-url.ts')
const URL_A = 'https://market.example/index.json', OTHER = 'https://other.example/index.json'
const rows: any[] = [], failure = (error: any) => ({ code: error.code ?? null, message: error.message, details: error.details ?? null })
for (const url of [' HTTPS://Example.COM:443/a/../index.json?q=1 ', 'http://localhost:80/a', 'file:///index.json',
  'relative', 'https://u:p@example.com/', 'https://example.com/#', 'https://例子.测试/市场',
  'https://127.1/index.json', 'https://[::1]:443/a', 'https:\\example.com\\a', '\u3000https://example.com/a\u3000']) {
  try { rows.push({ step: 'url', input: url, value: normalizeIndexUrl(url) }) }
  catch (error) { rows.push({ step: 'url', input: url, error: failure(error) }) }
}
const ctx = new Context(), calls: string[] = [], gates: any[] = []; let config: any, now = 1000
class Manager extends Service { constructor(inner: any) { super(inner, 'pluginManager') } listBundles() { return [] } listVersionExemptions() { return { exemptions: {} } } }
class Settings extends Service { constructor(inner: any) { super(inner, 'settings') } async update(_id: any, patch: any) { return patch } }
class Capture extends Market { constructor(inner: any, resolved: any) { Object.defineProperty(inner.fiber, 'entry', { value: { options: { id: 'market' } } }); super(inner, resolved); config = resolved } }
await ctx.plugin(Manager); await ctx.plugin(Settings); await ctx.plugin(Capture, { indexes: [URL_A], cacheTtlMs: 100, detailCacheDir: '/nonexistent/plugin-market-detail-cache' })
const market: any = ctx.pluginMarket, saved = Date.now; Date.now = () => now
market.fetchIndex = (url: string) => {
  calls.push(url); const gate = Promise.withResolvers(); gates.push(gate)
  const abort = () => gate.reject(market.lifetime.signal.reason)
  market.lifetime.signal.addEventListener('abort', abort, { once: true })
  return gate.promise.finally(() => market.lifetime.signal.removeEventListener('abort', abort))
}
const urls = (value: string[]) => updateVolatile(config.indexes, Market.Config({ indexes: value }).indexes)
const pump = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
const snapshot = (step: string, extra = {}) => rows.push({ step, calls: calls.length, indexes: market.listIndexes(), ...extra })
const read = async (title: string, refresh = false, pin?: number) => {
  const count = gates.length, task = market.document(URL_A, refresh, pin); await pump()
  if (gates.length > count) gates.at(-1).resolve({ title, plugins: [] })
  return await task
}
try {
  snapshot('initial')
  const first = market.document(URL_A, false), second = market.document(URL_A, false); await pump()
  rows.push({ step: 'sharing', calls: calls.length, pending: market.pending.size })
  gates.at(-1).resolve({ title: 'A', plugins: [] }); const [a, b] = await Promise.all([first, second])
  snapshot('shared-result', { same: a === b, fetchedAt: a.fetchedAt })
  let value = await read('unused'); snapshot('cached', { fetchedAt: value.fetchedAt })
  value = await read('B', true); snapshot('refresh', { fetchedAt: value.fetchedAt })
  now = 1100; value = await read('unused', false, value.fetchedAt); snapshot('pinned-expired', { fetchedAt: value.fetchedAt })
  value = await read('C'); snapshot('expired', { fetchedAt: value.fetchedAt })
  let task = market.document(URL_A, true); await pump(); gates.at(-1).reject(Error('offline'))
  try { await task } catch (error) { snapshot('failed-keeps-title', { error: failure(error) }) }
  value = await read('D', true); snapshot('success-clears-error', { fetchedAt: value.fetchedAt })
  for (const target of [OTHER, 'https://EXAMPLE.com:443/index.json', 'https://u:p@example.com/']) {
    if (target !== OTHER) urls([...config.indexes.get(), target])
    try { await market.document(target, false) } catch (error) { rows.push({ step: 'refusal', error: failure(error) }) }
  }
  urls([URL_A, URL_A, 'https://EXAMPLE.com:443/index.json', 'https://u:p@example.com/']); snapshot('configured-refusals')
  for (const replacement of [[URL_A, ' https://other.example:443/index.json '],
    ['https://EXAMPLE.com:443/index.json', 'https://example.com/index.json'], ['https://u:p@example.com/', URL_A], ['relative']]) {
    let replacementValue: any
    const settings: any = ctx.settings; settings.update = async (_id: any, patch: any) => { replacementValue = patch.indexes }
    try { await market.setIndexes(replacement); rows.push({ step: 'replace', value: replacementValue }) }
    catch (error) { rows.push({ step: 'replace', error: failure(error) }) }
  }
  urls([]); ctx.emit('loader/volatile-update', [['indexes']]); snapshot('removed')
  urls([URL_A]); task = market.document(URL_A, false); await pump(); urls([]); gates.at(-1).resolve({ title: 'Late', plugins: [] }); await task
  urls([URL_A]); snapshot('late-success-not-retained')
  task = market.document(URL_A, false); await pump(); urls([]); gates.at(-1).reject(Error('late failure')); try { await task } catch {}
  urls([URL_A]); snapshot('late-failure-not-retained')
  // A caller withdrawing interest does not cancel the shared Source promise.
  task = market.document(URL_A, false); await pump(); snapshot('caller-cancel-keeps-shared', { pending: market.pending.size })
  const other = market.document(URL_A, false); gates.at(-1).resolve({ title: 'Still shared', plugins: [] }); await other; await task
  snapshot('other-caller-completes')
  task = market.document(URL_A, true); await pump(); await ctx.fiber.dispose()
  try { await task } catch (error) { rows.push({ step: 'dispose', error: failure(error), pending: market.pending.size, aborted: market.lifetime.signal.aborted }) }
} finally { Date.now = saved; await ctx.fiber.dispose() }
console.log(JSON.stringify(rows))
