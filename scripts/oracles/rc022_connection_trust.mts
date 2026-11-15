import {readFile} from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const {isTrustedApiRequest,isRemoteAuthority}=await load('packages/client/connection/src/api-request-trust.ts')
const rows=JSON.parse(await readFile(process.argv[3],'utf8'))
process.stdout.write(JSON.stringify([...rows.map((row:any,index:number)=>({index,allowed:isTrustedApiRequest(row.request,row.trusted,row.bind??undefined,row.protocol)})),...['localhost','127.1','[::1]','remote.example','10.1.2.3','invalid:port'].map(authority=>({authority,remote:isRemoteAuthority(authority)}))]))
