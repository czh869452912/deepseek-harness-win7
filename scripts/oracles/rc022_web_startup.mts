import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {provideCmdline,internals}=await load('packages/boot/cmdline/src/index.ts')
const startup=await load('packages/bundle/web-app/src/startup.ts')
const corpus=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows=[]
const stdout=internals.stdout,stderr=internals.stderr
try{for(const args of corpus){
 const ctx=new Context(),exits:number[]=[],chunks:string[]=[]
 const stream={write:(value:string)=>{chunks.push(value);return true}}
 internals.stdout=stream as any;internals.stderr=stream as any
 try{
  provideCmdline(ctx,{args,exit:(code:number)=>exits.push(code)})
  await ctx.plugin(startup);await Promise.resolve()
  rows.push({args,values:ctx.get('webStartup')??null,exits,out:chunks.join('')})
 }finally{await ctx.fiber.dispose()}
}}finally{internals.stdout=stdout;internals.stderr=stderr}
process.stdout.write(JSON.stringify(rows))
