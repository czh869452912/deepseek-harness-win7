import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {createHash} from 'node:crypto'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {Context} from '../../reference/vendor/cordis/src/index.ts'
import {Session,SessionId} from '../../reference/packages/core/session/src/index.ts'
import {RuntimeContextProjection} from '../../reference/packages/core/agent-loop/src/runtime-context.ts'
import * as helpers from '../../reference/packages/llm/llm/src/message.ts'

const root=fileURLToPath(new URL('../../',import.meta.url))
const casesPath=resolve(root,'scripts/oracles/message-values-cases.json')
const cases=JSON.parse(readFileSync(casesPath,'utf8'))
const rows=[]
for(const {name,helper,input} of cases){
  const before=structuredClone(input)
  const message=helpers[helper](input)
  const borrowed={input:input.extra??input.source,message:message.extra??message.source}
  rows.push({name,helper,inputUnchanged:JSON.stringify(input)===JSON.stringify(before),
    detached:borrowed.input===undefined||borrowed.message===undefined||borrowed.input!==borrowed.message,
    allocated:helper!=='freezeMessage',message,frozen:Object.isFrozen(message),
    contentFrozen:Object.isFrozen(message.content),sourceFrozen:Object.isFrozen(message.source)})
}
function encode(value:any){
  const objects:any[]=[],indexes=new Map<any,number>(),nodes:any[]=[]
  function atom(item:any):any{
    if(item===null||typeof item!=='object')return {value:item}
    if(!indexes.has(item)){indexes.set(item,objects.length);objects.push(item)}
    return {ref:indexes.get(item)}
  }
  const identity=atom(value)
  for(let position=0;position<objects.length;position++){
    const item=objects[position]
    const values=Array.isArray(item)?item.map(atom):Object.keys(item).sort().map(key=>[key,atom(item[key])])
    nodes.push({type:Array.isArray(item)?'array':'object',frozen:Object.isFrozen(item),values})
  }
  return {root:identity,nodes}
}
const shared:any={flag:false,count:0,empty:[]}
const graph:any={id:'preserved-graph',role:'user',source:{kind:'user',shared},content:[{type:'text',text:'graph'}],extra:{first:shared,second:shared}}
graph.extra.self=graph.extra
graph.extra.message=graph
shared.empty.push(shared.empty,graph)
const first=helpers.freezeMessage(graph)
const second=helpers.freezeMessage(first)
rows.push({name:'graph-first',detached:first!==graph,message:encode(first)})
rows.push({name:'graph-repeat',detached:second!==first,message:encode(second)})
for(const [name,current,sections,previous] of [
  ['projection-empty','',[],null],['projection-current','new',[],null],
  ['projection-section','new',[{name:'policy',text:'new'}],null],
  ['projection-same','old',[],'old'],['projection-changed','new',[],'old'],
  ['projection-cleared','',[],'old'],
] as const){
  const ctx=new Context()
  try{
    const session=Session.create(SessionId('message-projection'))
    if(previous!==null)session.append('user/message',helpers.freezeMessage({id:'retained-id',role:'user',
      content:[{type:'text',text:previous}],source:{kind:'plugin',plugin:'@deepseek-ai/dsh-system-prompt'}}),{surfaceOp:'append'})
    const projection=new RuntimeContextProjection(ctx,session)
    const message=projection.project(current,sections)
    rows.push(message===undefined?{name,present:false,allocated:false}:{name,present:true,allocated:true,message,
      frozen:Object.isFrozen(message),contentFrozen:Object.isFrozen(message.content),sourceFrozen:Object.isFrozen(message.source)})
  }finally{await ctx.fiber.dispose()}
}
writeFileSync(process.env.DSH_MESSAGE_VALUES_OUTPUT!,JSON.stringify({
  sourceCommit:execFileSync('git',['-C',resolve(root,'reference'),'rev-parse','HEAD'],{encoding:'utf8'}).trim(),
  node:process.version,casesSha256:createHash('sha256').update(readFileSync(casesPath)).digest('hex'),
  fixtureSha256:createHash('sha256').update(readFileSync(fileURLToPath(import.meta.url))).digest('hex'),rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
