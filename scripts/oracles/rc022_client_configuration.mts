import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),rows:any[]=[]
for(const [slug,configs] of Object.entries({shortcuts:[{}, {stopSequenceMs:700},{stopSequenceMs:2147483646},{stopSequenceMs:0},{stopSequenceMs:2147483647},{stopSequenceMs:1.5}],
 'ui-sidebar-documentpreview':[{}, {office:{maxPending:3},excel:{maxCells:1200}},{office:{maxReaders:0}},{excel:{timeoutMs:2147483648}},{office:{maxCachedBytes:9007199254740992}}]})){
 const module=await load('packages/client/'+slug+'/src/index.ts')
 for(const config of configs){const ctx=new Context();let result:any
  try{let parsed:any;try{parsed=module.Config(config)}catch{rows.push({slug,config,accepted:false});continue}
   const fiber=await ctx.plugin(module,parsed),before:any[]=[];ctx.emit('webserver/index-inject',before,{principal:{kind:'owner'}});await fiber.dispose();const after:any[]=[];ctx.emit('webserver/index-inject',after,{principal:{kind:'owner'}})
   result={slug,config,accepted:true,before,after}
  }finally{await ctx.fiber.dispose()}
  rows.push(result)
 }
}
process.stdout.write(JSON.stringify(rows))
