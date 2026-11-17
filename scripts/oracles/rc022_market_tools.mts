import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
import {definition} from './rc022_market_definition.mts'
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),{Context}=await load('vendor/cordis/src/index.ts'),ctx=new Context(),requests:any[]=[],rows:any[]=[]
const market={listIndexes:()=>[{url:'market'},{url:'offline',title:{en:'Market',zh:'市场'},error:'offline'}],search:async(target:string,request:any)=>{requests.push([target,request]);return {title:{en:'Market'},entries:input.entries,total:2,nextOffset:null}},entry:async(target:string,name:string)=>name==='bundle'?input.entries[0]:undefined}
const Provider={apply:(scope:any)=>{scope.provide('pluginMarket');scope.pluginMarket=market}}
const {executeToolFixture}=await load('packages/test-support/tool-testkit/src/index.ts')
try{
 for(const path of ['packages/core/system-prompt/src/index.ts','packages/core/tools/src/index.ts','packages/core/tool-executor-native/src/index.ts']){const module=await load(path);await ctx.plugin(module.default??module)}
 const fiber=await ctx.plugin(await load('packages/boot/plugin-market/src/tools.ts'));rows.push({name:'absent',visible:ctx.tools.get('plugin_market')!==undefined})
 const provider=await ctx.plugin(Provider);rows.push({name:'descriptor',value:await definition()})
 for(const [index,args] of input.cases.entries()){
  const before=requests.length,result=await executeToolFixture(ctx,{callId:'market-'+index,name:'plugin_market',arguments:args,signal:new AbortController().signal})
  rows.push({name:String(index),value:{isError:result.isError,value:result.value??null,content:result.content},requests:requests.slice(before),presentation:ctx.tools.get('plugin_market').presentCall(args)??null})
 }
 await provider.dispose();rows.push({name:'withdrawn',visible:ctx.tools.get('plugin_market')!==undefined});await fiber.dispose();console.log(JSON.stringify(rows))
}finally{await ctx.fiber.dispose()}
