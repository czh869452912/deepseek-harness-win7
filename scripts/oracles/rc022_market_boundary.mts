import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {default: Market} = await load('packages/boot/plugin-market/src/index.ts')
const input = JSON.parse(readFileSync(process.argv[3], 'utf8'))
const market = Object.create(Market.prototype)
market.config = {fetchTimeoutMs:15000, maxBytes:input.limit}
market.lifetime = new AbortController()
const rows = []
for (const kind of input.cases) {
 try { rows.push({kind, ok:true, index:await market.fetchIndex(input.base+'/'+kind)}) }
 catch(error:any) { rows.push({kind, ok:false, code:error.code??null, message:error.message, details:error.details??null}) }
}
console.log(JSON.stringify(rows))
