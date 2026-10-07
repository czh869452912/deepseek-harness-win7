import {execFileSync} from 'node:child_process'
import {writeFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {FsSandboxController} from '../../reference/packages/fs/tool-fs/src/sandbox.ts'
import {FsError} from '@deepseek-ai/dsh-fs'

const root=fileURLToPath(new URL('../../',import.meta.url))
const names=['unconfined','missing-policy','ordinary','mode-only','reason-only','empty-reason','same-mode','narrower-mode',
  'missing-approval','missing-agent','granted','rejected','cancelled','unavailable','lower-standing',
  'highest-standing','unconfined-request','captured-policy','mutated-policy','provider-error','denied-error','other-error']
const rows:any[]=[]
for(const name of names){
  const trace:any[]=[]
  const standing:any={mode:name==='lower-standing'?'read-only':name==='highest-standing'?'danger-full-access':'workspace-write',workspaceRoot:'C:/fixture',temporaryRoots:['C:/temp']}
  const oldPolicy={resolve:(options:any)=>{trace.push({kind:'policy',sessionPresent:options.session!==undefined});return standing}}
  let selectedPolicy:any=name==='missing-policy'?undefined:oldPolicy
  const agent:any=name==='missing-agent'?undefined:{session:{id:'session-fixture'}}
  const signal=new AbortController().signal
  const approval=name==='missing-approval'?undefined:{request:async(request:any)=>{
    trace.push({kind:'ask',toolName:request.toolName,callId:request.callId,reason:request.reason,agentSame:request.agent===agent,signalSame:request.signal===signal})
    if(name==='mutated-policy')standing.temporaryRoots.push('C:/changed')
    return ['rejected','cancelled','unavailable'].includes(name)?name:'allowed-once'
  }}
  const ctx:any={fs:{sandboxMode:['unconfined','unconfined-request'].includes(name)?undefined:'danger-full-access'},get:(key:string)=>key==='sandboxPolicy'?selectedPolicy:key==='approval'?approval:undefined}
  const observation:any={name,trace}
  try{
    const sandbox=new FsSandboxController(ctx)
    observation.schema=sandbox.escalationModes.length?sandbox.schemaFields():{}
    if(name==='captured-policy')selectedPolicy={resolve:()=>{throw new Error('replacement must not resolve')}}
    const args:any={}
    if(!['unconfined','ordinary','provider-error','denied-error','other-error'].includes(name))Object.assign(args,{sandbox_permissions:'danger-full-access',justification:'Wider access for this exact operation.'})
    if(name==='mode-only')delete args.justification
    if(name==='reason-only')delete args.sandbox_permissions
    if(name==='empty-reason')args.justification=' '
    if(name==='same-mode')args.sandbox_permissions='workspace-write'
    if(name==='narrower-mode')args.sandbox_permissions='read-only'
    if(name==='lower-standing')args.sandbox_permissions='workspace-write'
    const policy=await sandbox.resolvePolicy('write',args,{agent,callId:'call-fixture',signal} as any)
    observation.policy=policy??null
    if(['provider-error','denied-error','other-error'].includes(name)){
      const original=name==='other-error'?new Error('ordinary provider failure'):new FsError('provider failure',name==='denied-error'?'FS_SANDBOX_DENIED':'FS_STALE_WRITE')
      const mapped:any=sandbox.mapError(original,policy)
      observation.mapping={same:mapped===original,message:mapped.message,code:mapped.code??null,causeSame:mapped.cause===original}
    }
  }catch(error:any){observation.error={message:error.message}}
  rows.push(observation)
}
writeFileSync(process.env.DSH_FS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
