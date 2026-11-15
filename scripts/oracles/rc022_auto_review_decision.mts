import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const ts=await load('node_modules/typescript/lib/typescript.js'), {BlockAssembler}=await load('packages/llm/llm/src/index.ts'),{deniedDisplayReason}=await load('packages/experimental/auto-review/src/locales.ts')
const source=readFileSync(resolve(process.argv[2]!, 'packages/experimental/auto-review/src/index.ts'),'utf8')
// Instrument private functions without reimplementing their protocol or loading the plugin.
const decoder=source.slice(source.indexOf('function topLevelMemberCount('),source.indexOf('/** Review one frozen pending action'))
const presentation=source.slice(source.indexOf('function denied('),source.indexOf('/** Install the Auto preset'))
const constants=source.slice(source.indexOf('const AUTO_REVIEW_DENIED_ERROR_NAME'),source.indexOf('/** Fixed policy'))
const code=ts.transpileModule(constants+decoder+presentation,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText
const {parseDecision,readDecision,denied,askUser,failed}=new Function('BlockAssembler','deniedDisplayReason',code+'\nreturn {parseDecision,readDecision,denied,askUser,failed}')(BlockAssembler,deniedDisplayReason)
const rows:any[]=[]
for(const item of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const error=Error('provider secret');let result,closed=false
 async function* stream(){try{for(const chunk of item.chunks)yield chunk;if(item.fail)throw error}finally{closed=true}}
 try{result=item.present?{denied:denied({name:'probe'},item.reason),ask:askUser({name:'probe'},item.reason),failed:failed({name:'probe'},error)}:{value:item.chunks?await readDecision(stream()):parseDecision(item.text)}}catch(failure:any){result={error:failure instanceof SyntaxError?{syntax:true}:{message:failure.message,original:failure===error}}}
 rows.push({name:item.name,result,...item.chunks?{closed}:{}})
}
console.log(JSON.stringify(rows))
