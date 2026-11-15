import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),z=(await load('vendor/schemastery/src/index.ts')).default,Loader=(await load('vendor/loader/src/index.ts')).default,Settings=(await load('packages/settings/settings/src/index.ts')).default,ctx=new Context(),rows:any[]=[],events:any[]=[]
const plugin={Config:z.object({ordinary:z.string().required(),count:z.number().min(1).default(2).volatile(),token:z.string().role('secret').volatile(),list:z.array(z.object({name:z.string().required(),token:z.string().role('secret')})).volatile()}),apply(){}}
const base={ordinary:'fixed',count:2,token:'private',list:[{name:'one',token:'secret'}]};let override:any={}
try{
 await ctx.plugin(Loader);ctx.provide('profileContext',{home:'C:/nonexistent-settings-legacy'});const fiber=await ctx.plugin(plugin,base),entry={id:'probe',options:{id:'probe',name:'cordis:probe',config:structuredClone(base)},fiber}
 ctx.provide('configEditor',{documentPath:'patch.yml',entries:()=>[entry],configuration:()=>[{entry,inherited:structuredClone(base),override:structuredClone(override)}],edit:async(_entry:any,change:any)=>{const value=change(structuredClone(entry.options.config),structuredClone(base));await fiber.update(value);entry.options.config=value;override=structuredClone(value)}});ctx.on('settings/document-updated',(ns:string,revision:number)=>events.push({ns,revision}));await ctx.plugin(Settings);const settings=ctx.settings
 function snapshot(name:string){const descriptor=settings.describe({redactSecrets:true})[0];delete descriptor.schema;rows.push({name,value:descriptor})}
 snapshot('initial');const policy=settings.configure({auto:false},fiber);snapshot('policy');await settings.update('probe',{count:3},0);snapshot('updated')
 try{await settings.update('probe',{count:4},0)}catch(error:any){rows.push({name:'conflict',code:error.code,expected:error.expected,actual:error.actual})}
 await settings.mutate('probe',[{op:'set',path:['list','0','name'],value:'renamed'}]);snapshot('mutated');await settings.mutate('probe',[{op:'unset',path:['count']}]);snapshot('inherited')
 try{await settings.update('probe',{ordinary:'changed'})}catch(error:any){rows.push({name:'ordinary-refusal',message:error.message})}
 await settings.replace('probe',{count:5});snapshot('replaced');rows.push({name:'raw',value:entry.options.config});policy();snapshot('policy-restored');rows.push({name:'events',values:events})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
