import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const child=await load('packages/subagent/subagent/src/child-agent.ts'),structured=await load('packages/subagent/subagent/src/structured.ts'),rows:any[]=[]
for(const preset of [null,'workspace-write','auto','danger-full-access']){
 const events:any[]=[],services:any={permissionPresets:{current:()=>preset??undefined},sandboxPolicy:{overrideOf:()=>'workspace-write'},approval:{},agentPresets:{composedPreset:()=>'live-parent'}},parent={ctx:{get:(name:string)=>services[name]},session:{header:{id:'parent',cwd:'C:/work'}}}
 const captured=child.captureDelegatedPolicyOverrides(parent);child.appendDelegatedPolicyOverrides({append:(type:string,data:any)=>events.push({type,data})},captured)
 rows.push({kind:'policy',preset,captured,events,inherited:child.childSessionMeta(parent,2,true),selected:child.childSessionMeta(parent,2,false,'other')})
}
for(const action of ['inherit','restore-host','selected','missing-preset']){
 const trace:any[]=[],presets={mount:async(_ctx:any,preset:string)=>{trace.push('mount:'+preset);await Promise.resolve();trace.push('mounted')},composeFrom:()=>trace.push('inherit')}
 const prompt={context:(value:any)=>trace.push({context:value}),section:(value:any)=>trace.push({section:value}),getContextOrder:(name:string)=>name,getSectionOrder:(name:string)=>name}
 const services:any={agentPresets:action==='missing-preset'?undefined:presets},ctx={get:(name:string)=>services[name],systemPrompt:prompt,tools:{restrict:(value:any)=>trace.push({restrict:value})}},composition:any={persona:'Historical',toolFilter:{deny:['secret']}}
 if(['selected','missing-preset'].includes(action))composition.agentPreset='coding';const row:any={kind:'composition',action}
 try{const operation=child.applyChildComposition(ctx,action==='restore-host'?undefined:{ctx:{}},composition);row.async=operation!==undefined;if(operation!==undefined)await operation}catch(error:any){row.error={code:error.code??null,message:error.message}}row.trace=trace;rows.push(row)
}
for(const action of ['pending-input','direct-success','direct-error','nested-success','nested-error','invalid']){
 let definition:any;const handlers:any={},guards:any[]=[],ctx={tools:{register:(value:any)=>definition=value,guard:(value:any)=>guards.push(value)},systemPrompt:{section(){},getSectionOrder(){return 0}},on:(event:string,callback:any)=>handlers[event]=callback}
 const attachment=structured.attachStructuredRuntime(ctx,{type:'object',properties:{ok:{type:'boolean'}},required:['ok'],additionalProperties:false},()=>action!=='pending-input')
 const parent=action.startsWith('nested')?{}:undefined,execution={name:'structured_output',parent,token:{},concluded:0,concludeTurn(){this.concluded++}},states=[attachment.acceptsInput()],row:any={kind:'structured',action}
 try{await definition.execute({ok:action==='invalid'?'wrong':true},execution)}catch{row.rejected=true}states.push(attachment.acceptsInput())
 if(!row.rejected){handlers['tools/result'](execution,{isError:action==='direct-error'});states.push(attachment.acceptsInput());row.guard=guards[0](execution)??null;if(parent!==undefined){handlers['tools/result']({name:'run_code',token:parent},{isError:action==='nested-error'});states.push(attachment.acceptsInput())}}
 Object.assign(row,{states,captured:attachment.captured()??null,concluded:execution.concluded});rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
