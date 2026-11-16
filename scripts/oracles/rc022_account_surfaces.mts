import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {plainConfig}=await load('packages/settings/settings/src/schema.ts')
const account=await load('packages/client/ui-settings-account/src/index.ts')
const notification=await load('packages/client/ui-account-notifications/src/index.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 const ctx=new Context(),calls:any[]=[],disposed:any[]=[]
 const settings={configure(policy:any,owner:any){calls.push({policy});return()=>disposed.push(true)}}
 if(entry.mode==='initial')ctx.provide('settings',settings)
 try{
  let fiber:any
  try{fiber=await ctx.plugin(entry.kind==='account'?account:notification,entry.config)}
  catch(error){rows.push({accepted:false});continue}
  if(entry.mode==='late'){ctx.provide('settings',settings);for(let i=0;i<3;i++)await Promise.resolve()}
  const table:any[]=[];ctx.emit('webserver/index-inject',table,{principal:{kind:'owner'}})
  const row=JSON.parse(JSON.stringify({accepted:true,config:plainConfig(fiber.effectiveConfig),table,calls}))
  await fiber.dispose()
  const after:any[]=[];ctx.emit('webserver/index-inject',after)
  Object.assign(row,{disposed:disposed.length,after});rows.push(row)
 }finally{await ctx.fiber.dispose()}
}
process.stdout.write(JSON.stringify(rows))
