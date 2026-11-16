import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const Tools=await load('packages/boot/plugin-manager/src/tools.ts')
const {getDshRuntimeVersion}=await load('packages/boot/app-boot/src/plugin-compatibility.ts')
const cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const test of cases){
 const calls:any[]=[],controller=new AbortController(),policy={mode:test.mode??'danger-full-access'}
 let definition:any
 const manager:any={listVersionExemptions:()=>{calls.push({op:'listVersionExemptions',args:[]});return{exemptions:[],warnings:[],...test.overrideVersion?{runtimeVersion:'manager-override'}:{}}}}
 for(const method of ['listPlugins','listBundles','setPluginEnabled','setBundleEnabled','installBundle','removeBundle','setVersionExemption'])manager[method]=async(...args:any[])=>{calls.push({op:method,args:args.map(value=>value??null)});return method.startsWith('list')?[{entryId:'first',meta:{private:true}},{name:'bundle',rows:[{id:'row',meta:{secret:true}}],meta:{private:true},update:{available:true},listedByDefault:true},{entryId:'last'}]:test.result??{application:'applied'}}
 const approval=test.noApproval?undefined:{request:async(request:any)=>{const {toolName,callId,reason,displayReason}=request;calls.push({op:'approval',toolName,callId,reason,displayReason});return test.approval??'allowed-once'}}
 const ctx={tools:{register:(value:any)=>{definition=value}},sandboxPolicy:{resolve:(options:any)=>{calls.push({op:'policy',hasSession:'session'in options});return policy}},pluginManager:manager,get:()=>approval}
 Tools.apply(ctx)
 if(test.aborted)controller.abort(new Error('cancelled'))
 let outcome
 try{const result=JSON.parse(await definition.execute(test.args,{agent:test.noAgent?undefined:{session:{}},callId:'call',signal:controller.signal}));if(test.name==='exemptions'){if(result.runtimeVersion!==getDshRuntimeVersion())throw new Error('runtime identity mismatch');result.runtimeVersion='<active-runtime>'}outcome={value:result}}catch(error:any){outcome={error:error.message}}
 rows.push({name:test.name,outcome,calls,mode:policy.mode,view:definition.presentCall(test.args),listeners:0})
}
process.stdout.write(JSON.stringify(rows))
