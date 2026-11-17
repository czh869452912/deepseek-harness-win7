import fs from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),Office=await load('packages/skill/skill-office/src/index.ts'),Registry=(await load('packages/skill/skill/src/index.ts')).default
const assets=resolve(process.argv[2]!,'packages/skill/skill-office/assets'),input=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const[index,entry]of input.cases.entries()){
 const root=join(input.directory,String(index)),docx=join(root,'office-docx','SKILL.md');await fs.cp(assets,root,{recursive:true});const original=await fs.readFile(docx)
 if('raw'in entry)await fs.writeFile(docx,entry.raw);if(entry.missing)await fs.unlink(docx)
 const ctx=new Context(),warnings:string[]=[];ctx.logger.warn=(message:any)=>{warnings.push(String(message))}
 let row:any
 try{
  await ctx.plugin(Registry);let fiber=await ctx.plugin(Office,{assetRoot:root,pythonEnvironment:entry.environment??'workspace-dependencies'})
  const catalog=await ctx.skills.snapshot(),loaded=[]
  for(const name of ['office','office-docx','office-pptx','office-xlsx'])loaded.push(await ctx.skills.get(name)??null)
  await ctx.skills.get('office-docx');const after=await ctx.skills.snapshot(),before=warnings.length
  await fiber.dispose();await fs.writeFile(docx,original);fiber=await ctx.plugin(Office,{assetRoot:root,pythonEnvironment:entry.environment??'workspace-dependencies'});const recovered=await ctx.skills.get('office-docx')
  await fiber.dispose();const removed=await ctx.skills.list();row={catalog,loaded,after,warnings:before,recovered,removed}
 }finally{await ctx.fiber.dispose()}
 function normalize(value:any):any{if(typeof value==='string')return value.replaceAll(root,'<assets>').replaceAll(root.replaceAll('\\','/'),'<assets>');if(Array.isArray(value))return value.map(normalize);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,normalize(v)]));return value}
 rows.push(normalize(row))
}
console.log(JSON.stringify(rows))
