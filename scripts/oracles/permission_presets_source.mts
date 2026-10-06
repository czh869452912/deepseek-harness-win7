import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import SessionStore,{SessionId} from '@deepseek-ai/dsh-session'
import PermissionPresetService from '@deepseek-ai/dsh-permission-presets'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import CommandRuntime from '@deepseek-ai/dsh-commands'
import ApprovalService from '@deepseek-ai/dsh-user-approval'
import {createScope} from '@deepseek-ai/dsh-scope'
import {SettingsProvider} from '@deepseek-ai/dsh-settings'

class MemorySettings extends SettingsProvider {
  readonly doc:Record<string,unknown>={}
  readonly writable=true
  protected load(){return Promise.resolve(structuredClone(this.doc))}
  protected persist(ns:any,section:any){this.doc[ns]=structuredClone(section);return Promise.resolve()}
}

const root=process.cwd()+'/'
const rows:any[]=[],rawErrors:any[]=[]
const ctx=new Context()
try{
  await ctx.plugin(SessionStore)
  ctx.provide('shell',{sandboxMode:'workspace-write'})
  await ctx.plugin(ApprovalService)
  await ctx.plugin(CommandRuntime)
  await ctx.plugin(SessionProjectionRegistry)
  const settingsFiber=await ctx.plugin(MemorySettings)
  const permissionFiber=await ctx.plugin(PermissionPresetService,{presets:{
    'workspace-write':{sandbox:'workspace-write',approval:'ask',name:'Workspace'},
    'danger-full-access':{sandbox:'danger-full-access',approval:'never',name:'Full',description:''},
  }})
  rows.push({name:'settings-labels',value:ctx.settings.describe()})
  const session=ctx.sessions.create(SessionId('permission-lifecycle'))
  rows.push({name:'initial-projection',value:ctx.sessionProjections.snapshot(session)})
  const definition=(ctx.sessionProjections as any).registrations.get('permissions').def
  const states:any[]=[{preset:null,sandbox:null,approval:null},{preset:'',sandbox:'read-only',approval:'never'},
    {preset:null,sandbox:'foreign',approval:null},{preset:null,sandbox:null,approval:'foreign'},
    {preset:null,sandbox:null,approval:null,extra:true},{preset:null,sandbox:null},
    {preset:5,sandbox:null,approval:null},null,[],{preset:'custom',sandbox:'workspace-write',approval:'ask'}]
  const views:any[]=[{options:[],currentValue:'custom'},{options:[{value:'v',name:'n',description:'',extra:1}],currentValue:'v',extra:1},
    {options:[{value:'v',name:'n'}],currentValue:'v'},{options:[{value:'',name:'n'}],currentValue:'v'},
    {options:[{value:'v',name:''}],currentValue:'v'},{options:[{value:'v',name:'n',description:null}],currentValue:'v'},
    {options:[],currentValue:''},{options:{},currentValue:'v'},null]
  for(const [kind,values,schema] of [['state',states,definition.stateSchema],['view',views,definition.wire.viewSchema]] as any){
    for(const [index,value] of values.entries()){
      const name=`${kind}-${index}`
      try{rows.push({name,value:schema.parse(value)})}
      catch(error:any){rows.push({name,refused:true});rawErrors.push({name,error:{name:error.name,message:error.message,issues:error.issues}})}
    }
  }
  const injected:any[]=[]
  const agent:any={id:session.id,session,inject:(value:any)=>injected.push(structuredClone(value))}
  await ctx.plugin(Object.assign((inner:Context)=>{createScope(inner,agent)},{inject:['commands']}))
  for(const line of ['/permission','/permission foreign','/permission danger-full-access','/permission danger-full-access','/permission workspace-write']){
    const execution=await ctx.commands.execute(agent,line,[],new AbortController().signal)
    rows.push({name:'command-'+rows.filter(row=>row.name.startsWith('command-')).length,line,
      value:execution?.result,current:ctx.permissionPresets.current(session.events),
      knobs:session.events.filter(event=>['permission/preset','sandbox/mode','approval/policy'].includes(event.type)).map(event=>({type:event.type,data:event.data})),
      approvalConfig:structuredClone(ctx.approval.config),injected:structuredClone(injected)})
  }
  await ctx.settings.replace('permission' as any,{defaultPreset:'danger-full-access'})
  rows.push({name:'live-default',value:ctx.permissionPresets.defaultPreset,descriptors:ctx.settings.describe()})
  const future=ctx.sessions.create(SessionId('permission-future'))
  rows.push({name:'future-default',value:ctx.sessionProjections.snapshot(future)})
  await settingsFiber.dispose()
  rows.push({name:'settings-detach',value:ctx.permissionPresets.defaultPreset})
  await permissionFiber.dispose()
  rows.push({name:'permission-unload',value:ctx.sessionProjections.snapshot(session),command:await ctx.commands.execute(agent,'/permission',[],new AbortController().signal)??null})
}finally{await ctx.fiber.dispose()}
writeFileSync(process.env.DSH_PERMISSION_PRESETS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows,rawErrors},null,2)+'\n',{encoding:'utf8',flag:'wx'})
