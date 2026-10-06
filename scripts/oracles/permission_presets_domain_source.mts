import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {Context} from '@deepseek-ai/cordis'
import SessionStore,{Session,SessionId} from '@deepseek-ai/dsh-session'
import PermissionPresetService from '@deepseek-ai/dsh-permission-presets'

const root=process.cwd()+'/'
const observedClock=1791283200000
const originalClock=Date.now
Date.now=()=>observedClock
const names=['fresh','mount-existing','inferred-danger','explicit-danger-default','selected-only','sandbox-only','approval-only','seed-empty','seed-historical','seed-custom','set-danger','set-noop','set-alias','stale-alias','custom-view','unknown-set','reserved-table','unconfined','unmatched-default','unknown-default','empty-description','empty-key','numeric-first','numeric-selected','numeric-boundary']
const rows=[]
for(const name of names){
  const ctx=new Context()
  const trace:any[]=[],rawEvents:any[]=[]
  let session:any
  const shellDefault=name==='inferred-danger'?'danger-full-access':name==='unconfined'?undefined:'workspace-write'
  const approvalDefault=['inferred-danger','unmatched-default'].includes(name)?'never':'ask'
  const config:any={}
  if(name==='explicit-danger-default')config.defaultPreset='danger-full-access'
  if(name==='unknown-default')config.defaultPreset='foreign'
  if(['set-alias','stale-alias','empty-description'].includes(name))config.presets={
    'workspace-write':{sandbox:'workspace-write',approval:'ask'},
    alias:{sandbox:'workspace-write',approval:'ask',name:'Alias',description:''},
    'danger-full-access':{sandbox:'danger-full-access',approval:'never'},
  }
  if(name==='reserved-table')config.presets={custom:{sandbox:'workspace-write',approval:'ask'}}
  if(name==='empty-key')config.presets={
    '':{sandbox:'workspace-write',approval:'ask',name:''},
    alias:{sandbox:'workspace-write',approval:'ask',name:'Alias'},
  }
  if(['numeric-first','numeric-selected'].includes(name))config.presets={
    '10':{sandbox:'workspace-write',approval:'ask',name:'Ten'},
    '2':{sandbox:'workspace-write',approval:'ask',name:'Two'},
    plain:{sandbox:'workspace-write',approval:'ask',name:'Plain'},
  }
  if(name==='numeric-boundary')config.presets={
    '4294967295':{sandbox:'workspace-write',approval:'ask'},
    '4294967294':{sandbox:'workspace-write',approval:'ask'},
    '01':{sandbox:'workspace-write',approval:'ask'},
    '0':{sandbox:'workspace-write',approval:'ask'},
  }
  const observation:any={name,config,shellDefault:shellDefault??null,approvalDefault,trace,rawEvents}
  try{
    await ctx.plugin(SessionStore)
    ctx.provide('shell',{sandboxMode:shellDefault})
    ctx.provide('approval',{config:{policy:approvalDefault}})
    ctx.on('session/event',(selected,event)=>rawEvents.push(structuredClone(event)))
    if(name==='mount-existing')session=ctx.sessions.create(SessionId('permission-fixture'))
    await ctx.plugin(PermissionPresetService,config)
    if(name==='seed-empty')session=ctx.sessions.create(SessionId('permission-fixture'),{seed:[]})
    else if(['seed-historical','seed-custom'].includes(name)){
      const prior=Session.create(SessionId('seed-fixture'))
      if(name==='seed-custom')prior.append('sandbox/mode',{mode:'read-only'})
      else{prior.append('turn/start',{turn:1});prior.append('turn/end',{turn:1,reason:{kind:'completed'}})}
      session=ctx.sessions.create(SessionId('permission-fixture'),{seed:prior.events})
    }else if(['selected-only','sandbox-only','approval-only','numeric-selected'].includes(name)){
      session=Session.create(SessionId('permission-fixture'))
      if(name==='selected-only')session.append('permission/preset',{preset:'danger-full-access'})
      if(name==='numeric-selected')session.append('permission/preset',{preset:'10'})
      if(name==='sandbox-only')session.append('sandbox/mode',{mode:'read-only'})
      if(name==='approval-only')session.append('approval/policy',{policy:'never'})
      ctx.sessions.enter(session)
      ctx.sessions.announce(session)
    }else if(!session)session=ctx.sessions.create(SessionId('permission-fixture'))
    if(name==='set-danger')ctx.permissionPresets.set(session,'danger-full-access')
    if(name==='set-noop')ctx.permissionPresets.set(session,'workspace-write')
    if(['set-alias','stale-alias'].includes(name))ctx.permissionPresets.set(session,'alias')
    if(name==='stale-alias'){session.append('sandbox/mode',{mode:'danger-full-access'});session.append('approval/policy',{policy:'never'})}
    if(name==='custom-view')session.append('sandbox/mode',{mode:'read-only'})
    if(name==='unknown-set')ctx.permissionPresets.set(session,'foreign')
    observation.result={names:ctx.permissionPresets.names,defaultPreset:ctx.permissionPresets.defaultPreset,
      current:ctx.permissionPresets.current(session.events),select:ctx.permissionPresets.selectFor(session.events.reduce((state,event)=>{
        if(event.type==='permission/preset')return {...state,preset:event.data.preset}
        if(event.type==='sandbox/mode')return {...state,sandbox:event.data.mode}
        if(event.type==='approval/policy')return {...state,approval:event.data.policy}
        return state
      },{preset:null,sandbox:null,approval:null})),approvalConfig:structuredClone(ctx.approval.config),
      events:session.events.map(event=>({type:event.type,data:event.data}))}
  }catch(error:any){observation.error={name:error.name,message:error.message}}
  finally{await ctx.fiber.dispose()}
  rows.push(observation)
}
Date.now=originalClock
writeFileSync(process.env.DSH_PERMISSION_DOMAIN_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,observedClock,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
