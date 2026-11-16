import fs from 'node:fs/promises'
import path from 'node:path'
import {createRequire} from 'node:module'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {createLaunchEnvironmentSnapshot,DSH_LAUNCH_ENVIRONMENT_KEY}=await load('packages/util/launch-environment/src/index.ts')
const {LocalCredentialProvider}=await load('packages/credentials/credentials-local/src/index.ts')
const yaml=createRequire(path.join(process.argv[2]!,'packages/credentials/credentials-local/package.json'))('yaml')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),directory=path.join(path.dirname(process.argv[3]!),'files/source'),rows:any[]=[]
await fs.mkdir(directory,{recursive:true})
for(const [index,entry]of inputs.entries()){
 const filename=path.join(directory,index+'.yaml'),ctx=new Context(),events:string[]=[]
 const initial={version:1,refs:entry.stored===null?{}:{TEST_KEY:entry.stored}}
 await fs.writeFile(filename,yaml.stringify(initial),{mode:0o600})
 const layers=[['process','process'],['project-env','project'],['user-env','user']].map(([source,key])=>({source,values:entry[key!]===null?{}:{TEST_KEY:entry[key!]}}))
 ctx.provide(DSH_LAUNCH_ENVIRONMENT_KEY,createLaunchEnvironmentSnapshot(layers))
 ctx.on('credentials/reference-updated',(ref:string)=>{events.push(ref)})
 try{
  await ctx.plugin(LocalCredentialProvider,{path:filename,watch:false})
  const snapshot=async()=>({value:await ctx.credentials.resolve('TEST_KEY')??null,info:await ctx.credentials.describe('TEST_KEY'),events:[...events]})
  const result:any[]=[await snapshot()]
  await ctx.credentials.set('TEST_KEY','new-provider_'+'z'.repeat(20));result.push(await snapshot())
  await ctx.credentials.unset('TEST_KEY');result.push(await snapshot())
  await ctx.credentials.unset('TEST_KEY');result.push(await snapshot())
  try{await ctx.credentials.set('TEST_KEY','')}catch(error:any){result.push({error:error.message})}
  const disk=yaml.parse(await fs.readFile(filename,'utf8'))
  rows.push({result,refs:disk.refs,layers})
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
