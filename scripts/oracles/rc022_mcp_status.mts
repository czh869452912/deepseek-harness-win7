import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {McpStatusCell,registerStatusCell,connectionStatusIn}=await load('packages/mcp/mcp-client/src/status.ts')
const {describeError,redactSecrets}=await load('packages/mcp/mcp-client/src/diagnostic.ts')
const {withDeadline}=await load('packages/mcp/mcp-client/src/deadline.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const trace:any[]=[],warns:any[]=[],cell=new McpStatusCell((message:any,error:any)=>warns.push(['old',message,describeError(error)]))
let release:any;const held=new Promise<void>(resolve=>release=resolve)
let removeOther:any
const late=(value:any)=>trace.push(['late',value.state])
cell.onChange((value:any)=>{trace.push(['first',value.state]);removeOther();cell.onChange(late)})
removeOther=cell.onChange((value:any)=>trace.push(['other',value.state]))
cell.onChange(()=>{trace.push('sync');throw new Error('sync failure')})
cell.onChange(async()=>{trace.push('async-start');await held;throw new TypeError('async failure')})
const value={state:'connected',toolCount:2,connectedAt:123};cell.update(value)
const before=[...trace],identity=cell.current()===value
cell.setWarningSink((message:any,error:any)=>warns.push(['new',message,describeError(error)]));release()
for(let i=0;i<6;i++)await Promise.resolve()
cell.opened();const opened=cell.closure();const closure={closeConfirmed:true,cleanupError:'observed'};cell.recordClosure(closure)
cell.update({state:'failed',reason:'gave-up'})
for(let i=0;i<6;i++)await Promise.resolve()
cell.detach();cell.update({state:'closed',result:closure})
const ctx=new Context();const unknown=connectionStatusIn(ctx.fiber)===undefined
const registered=registerStatusCell(ctx.fiber,()=>{}),again=registerStatusCell(ctx.fiber,()=>{})
const lookup=connectionStatusIn(ctx.fiber)===registered;await ctx.fiber.dispose()
const lifetime={unknown,same:registered===again,lookup,readable:connectionStatusIn(ctx.fiber)===registered}
const diagnostics=input.diagnostics.map((spec:any)=>{
 function build(row:any):any{
  if(!row||!row.error)return row?.value
  const error:any=row.name==='TypeError'?new TypeError(row.message):new Error(row.message);if(row.name!==undefined)error.name=row.name;if(row.code!==undefined)error.code=row.code
  if(row.cause!==undefined)error.cause=build(row.cause)
  if(row.cycle)error.cause=error
  return error
 }
 return describeError(build(spec))
})
let finish:any;const pending=new Promise<number>(resolve=>finish=resolve);let deadline
const keepAlive=setInterval(()=>{},100)
try{await withDeadline(pending,1,'deadline exceeded')}catch(error){deadline=describeError(error)}
finish(7);const lateValue=await pending;clearInterval(keepAlive)
let wrapped
try{await withDeadline(Promise.reject({fixture:1}),100,'unused')}catch(error){wrapped=describeError(error)}
process.stdout.write(JSON.stringify({before,trace,warns,identity,opened,closureIdentity:cell.closure()===closure,current:cell.current(),lifetime,diagnostics,redacted:input.redactions.map((row:any)=>redactSecrets(row.text,row.secrets)),deadline,lateValue,wrapped}))
