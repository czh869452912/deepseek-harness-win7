/** Reproduce the fixed Source's inert catalog without importing any provider. */
import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {readFileSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './oracles/rc022_subagent_fixture.mts'
const source=process.argv[2]!,output=process.argv[3]!,expected='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
if(execFileSync('git',['rev-parse','HEAD'],{cwd:source,encoding:'utf8'}).trim()!==expected)throw Error('wrong Source identity')
execFileSync('git',['diff','--exit-code','HEAD','--'],{cwd:source})
const module=await load('packages/util/official-bundles/src/index.ts')
const paths=['index.ts','bundles.ts','plugin-manager.ts','catalog.generated.ts'],inputs=Object.fromEntries(paths.map(path=>['packages/util/official-bundles/src/'+path,createHash('sha256').update(readFileSync(join(source,'packages/util/official-bundles/src',path))).digest('hex')]))
const data={upstream:expected,inputs,optionalBundles:module.OPTIONAL_BUNDLES,protectedPlugins:[...module.PROTECTED_PLUGINS],catalog:module.OFFICIAL_ON_DEMAND_CATALOG}
writeFileSync(output,JSON.stringify(data,null,2)+'\n',{flag:'wx'})
console.log(JSON.stringify({output,optional:data.optionalBundles.length,protected:data.protectedPlugins.length,catalog:data.catalog.length}))
