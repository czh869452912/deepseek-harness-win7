import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{evaluate}=await load('vendor/loader/src/config/utils.ts'),{dshHomePath}=await load('packages/util/home-paths/src/index.ts')
const input=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
const old=process.env.DSH_PRIMARY_RUNTIME,home=process.env.DSH_HOME
try{
 process.env.DSH_HOME=input.home
 for(const entry of input.cases){
  if(entry.value===null)delete process.env.DSH_PRIMARY_RUNTIME;else process.env.DSH_PRIMARY_RUNTIME=entry.value
  const ctx=new Context();if(entry.profile!==null)ctx.provide('profileContext',{name:entry.profile});ctx.provide('dshHomePath',dshHomePath)
  try{rows.push(input.expressions.map((expression:string)=>evaluate(ctx,expression)))}finally{await ctx.fiber.dispose()}
 }
}finally{if(old===undefined)delete process.env.DSH_PRIMARY_RUNTIME;else process.env.DSH_PRIMARY_RUNTIME=old;if(home===undefined)delete process.env.DSH_HOME;else process.env.DSH_HOME=home}
console.log(JSON.stringify(rows))
