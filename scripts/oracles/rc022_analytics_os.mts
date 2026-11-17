import {load} from './rc022_subagent_fixture.mts'
const {collectEnvironment}=await load('packages/client/product-analytics/src/environment.ts')
console.log(JSON.stringify(await collectEnvironment({timeoutMillis:5000,maxOutputBytes:16384,signal:new AbortController().signal})))
