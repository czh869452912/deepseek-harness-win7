import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {McpTemplateBinding}=await load('packages/mcp/mcp-client/src/credentials.ts')
const {assertTemplateSyntax,credentialRefsIn,resolveTemplateString,MissingTemplateValue}=await load('packages/mcp/mcp-client/src/templates.ts')
const {describeError}=await load('packages/mcp/mcp-client/src/diagnostic.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const text of input.strings){
 let syntax
 try{assertTemplateSyntax(text,'fixture');syntax={ok:true}}catch(error){syntax={error:describeError(error)}}
 const calls:any[]=[];let resolved
 try{resolved={value:await resolveTemplateString(text,'fixture',async(ref:string)=>{calls.push(ref);return input.values[ref]})}}catch(error){resolved={error:describeError(error),missing:error instanceof MissingTemplateValue}}
 rows.push({kind:'string',refs:credentialRefsIn(text),syntax,resolved,calls})
}
for(const spec of input.bindings){
 const ctx=new Context(),calls:any[]=[];let attempt:any,controller:any
 const provider={async resolve(ref:string){calls.push(ref);if(attempt.abortOn===ref)controller.abort(new Error('cancel resolution'));await Promise.resolve();return attempt.values[ref]===undefined?undefined:{value:attempt.values[ref],source:'fixture'}}}
 if(spec.provider)ctx.provide('credentials',provider)
 let row:any={kind:'binding',name:spec.name}
 try{
  const binding=new McpTemplateBinding(ctx,spec.config);row.refs=[...binding.refs];row.attempts=[]
  for(attempt of spec.attempts){
   controller=new AbortController();if(attempt.aborted)controller.abort(new Error('abort before'))
   if(attempt.removeProvider)ctx.set('credentials',undefined)
   if(attempt.restoreProvider)ctx.set('credentials',provider)
   const before=calls.length;let result:any
   try{const resolved=await binding.resolve(controller.signal);result={config:resolved,sameRaw:resolved===spec.config}}catch(error){result={error:describeError(error),missing:error instanceof MissingTemplateValue}}
   row.attempts.push({result,calls:calls.slice(before),redacted:binding.redact(input.redact),diagnostic:binding.diagnostic(new Error(input.redact),'connect')})
  }
 }catch(error){row.error=describeError(error)}
 finally{await ctx.fiber.dispose()}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
