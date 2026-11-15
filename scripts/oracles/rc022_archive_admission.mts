import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href),{installSubagentArchiveAdmission}=await load('packages/subagent/subagent/src/archive-admission.ts'),rows:any[]=[]
for(const action of ['headers','resident','inherited-label','idle','offline','ordinary-fork','cycle','stop-failure','no-workspace','no-running']){
 const trace:string[]=[],hooks:any={},agent=(id:string,parent?:string,origin?:string,own=true)=>({id,status:'running',session:{header:{id,...parent?{parentSession:parent}:{},...origin?{origin}:{}},isOwnSeq:()=>own},cancel:(_reason:any)=>{trace.push(id)}})
 const root=agent('root'),parent=agent('parent','root','subagent'),child=agent('child','parent','subagent',action!=='inherited-label'),live=new Map([root,parent,child].map(agent=>[agent.id,agent]))
 if(action==='idle')parent.status='idle';else if(action==='offline')live.delete('parent');else if(action==='ordinary-fork')delete parent.session.header.origin
 else if(action==='cycle')parent.session.header.parentSession='child';else if(action==='stop-failure')parent.cancel=()=>{trace.push('parent');throw Error('cancel failed')};else if(action==='no-running'){parent.status='idle';child.status='idle'}
 const services:any={workspaceRegistry:{archivedSessionIds:['root']}},ctx={agents:{get:(id:string)=>live.get(id),list:()=>[...live.values()]},get:(name:string)=>services[name],on:(event:string,callback:any)=>hooks[event]=callback,logger:{warn:()=>trace.push('warning')}}
 if(action==='no-workspace')delete services.workspaceRegistry
 installSubagentArchiveAdmission(ctx,(value:any)=>action==='resident'&&value===child?['root','parent']:undefined,()=>({seq:1,label:'Label'}))
 const activity=await hooks['workspace/session-activity']({sessionId:'root'},()=>[{kind:'other',items:[]}]),decision=await hooks['agent/pre-step']({agent:child},()=>({kind:'enter'}));hooks['workspace/session-stop']({sessionId:'root'});rows.push({action,activity,decision,trace})
}
process.stdout.write(JSON.stringify(rows))
