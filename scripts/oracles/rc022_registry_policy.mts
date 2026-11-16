import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const policy=await load('packages/boot/plugin-manager/src/registry.ts'),versions=await load('packages/boot/plugin-manager/src/versions.ts'),spec=await load('packages/boot/plugin-manager/src/install-spec.ts')
const data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
function result(operation:any){try{return {value:operation()}}catch{return {error:true}}}
for(const url of data.urls)rows.push({kind:'url',input:url,result:result(()=>policy.normalizeRegistry(url))})
for(const item of data.plans)rows.push({kind:'plan',input:item,result:result(()=>policy.registryPlan(item.requested,item.configured))})
for(const item of data.failures)rows.push({kind:'failure',input:item,value:policy.attributeFailure(item.kind,item.log,spec.parseInstallSpec(item.spec))})
for(const item of data.versions)rows.push({kind:'versions',input:item,result:result(()=>versions.newerVersions(item.answer,item.installed))})
for(const item of data.facts)rows.push({kind:'facts',input:item,value:versions.versionFacts(item,'fallback','1.0.0')})
console.log(JSON.stringify(rows))
