import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Inventory}=await load('packages/host/plugin-inventory/src/index.ts'),rows:any[]=[]
for(const name of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const ctx=new Context(),calls:any[]=[],error=Error('metadata unavailable'),parents:any={}
 for(const [kind,base] of [['root','file:///C:/root/'],['nested','file:///C:/nested/']])parents[kind]={tree:{ctx:name==='no-base'&&kind==='root'?{}:{baseUrl:base}}}
 if(name!=='no-base')ctx.baseUrl='file:///C:/root/'
 const fiber=(state:number)=>({state,await:async()=>{calls.push('await-failed');if(name==='failed-success')return;if(name==='failed-value')throw {reason:'raw'};throw Error('startup failure')}})
 const entries:any[]=name==='empty'?[]:[...Array.from({length:6},(_,state)=>({id:'state-'+state,options:{name:'plugin-'+state},fiber:fiber(state),disabled:state===0,parent:parents.root})),{id:'group',options:{group:true,name:'group'},fiber:undefined,disabled:false,parent:parents.root},{id:'nested',options:{name:'nested-plugin'},fiber:undefined,disabled:true,parent:parents.nested}]
 const services:any={loader:{entries:()=>entries}}
 if(name!=='no-packages')services.pluginPackages={metaOf:(module:string,base:string)=>{calls.push({meta:[module,base]});if(name==='metadata-error')throw error;return module==='plugin-1'?undefined:{name:{en:module,zh:'插件 '+module},description:base}}}
 if(name!=='no-presets')services.agentPresets={compositionInventory:async()=>{calls.push('compositions');if(name==='preset-error')throw error;return [{id:'engineering',name:'Engineer',isDefault:true,rows:[{entryId:'tool',moduleName:'tool-fs',enabled:'conditional',condition:'!ctx.fs'},{entryId:null,moduleName:'plugin-1',enabled:false,fiberState:2}]},{id:'broken',isDefault:false,broken:'unreadable preset',rows:[]}]}}
 if(name!=='no-manager')services.pluginManager={}
 for(const [key,value] of Object.entries(services)){ctx.provide(key);ctx[key]=value}
 const owner=await ctx.plugin(Inventory)
 try{
  let result
  try{const first=await ctx.pluginInventory.list();entries.push({id:'late',options:{name:'late-plugin'},fiber:fiber(2),disabled:false,parent:parents.nested});result={first,second:await ctx.pluginInventory.list()}}catch(failure:any){result={error:failure.message,original:failure===error}}
  await owner.dispose();rows.push({name,result,calls,withdrawn:ctx.get('pluginInventory')===undefined})
 }finally{await ctx.fiber.dispose()}
}
console.log(JSON.stringify(rows))
