import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {default:Manager}=await load('packages/subagent/subagent/src/manager.ts'),{default:Runtime}=await load('packages/subagent/subagent/src/index.ts'),rows:any[]=[]
const agent=(id:string,origin?:string,own=false)=>({id,session:{header:{id,...origin?{origin}:{}},isOwnSeq:()=>own}})
for(const action of ['root','ordinary-fork','own-descriptor','origin','resident','creator-gone','stale-caller','stale-root','stale-activation','external','named','unnamed','unnamed-parent','tree-closing','child-closing','manager-closing','name-lead','name-known','name-id','name-missing-path']){
 const root=agent('root'),parent=agent('parent','subagent',true),child=agent('child','subagent',true),ordinary=agent('ordinary'),live=new Map([root,parent,child,ordinary].map(agent=>[agent.id,agent]))
 const query=async(id:string)=>({projections:{values:{subagentCatalog:id==='root'?[{id:'child',mode:'continuable',name:'worker',label:'Task',createdAt:1}]:[]}},[Symbol.dispose](){}})
 const ctx={agents:{get:(id:string)=>live.get(id)},get:(name:string)=>name==='sessionQuery'?{observeSession:query}:undefined}
 const tree=Object.assign(Object.create(Manager.prototype),{ctx,host:{identityOf:(session:any)=>session===root.session?undefined:{seq:1}},resident:new Map(),closingRoots:new Set(),draining:false})
 const pa:any={kind:'local',handle:{agent:parent},root,ancestors:['root'],path:'worker',closing:undefined},activation:any={kind:'local',handle:{agent:child},root,ancestors:['root','parent'],path:'worker/nested',closing:undefined}
 tree.resident.set('parent',pa);tree.resident.set('child',activation);let caller=child
 if(action==='root')caller=root;else if(action==='ordinary-fork')caller=ordinary
 else if(action==='own-descriptor'){caller=agent('own',undefined,true);live.set(caller.id,caller)}
 else if(action==='origin'){caller=agent('origin','subagent');live.set(caller.id,caller)}
 else if(action==='creator-gone'){live.delete('parent');tree.resident.delete('parent')}
 else if(action==='stale-caller')live.set('child',agent('child'));else if(action==='stale-root')live.set('root',agent('root'))
 else if(action==='stale-activation')activation.handle.agent=agent('child');else if(action==='external')activation.kind='external'
 else if(action==='unnamed')activation.path=undefined;else if(action==='unnamed-parent'){activation.path=undefined;tree.resident.delete('parent')}
 else if(action==='tree-closing')tree.closingRoots.add(root);else if(action==='child-closing')activation.closing={};else if(action==='manager-closing')tree.draining=true
 const row:any={kind:'live',action}
 try{
  if(action.startsWith('name-'))row.value=await Runtime.prototype.resolveName.call({ctx,rootOf:(caller:any)=>tree.rootOf(caller)},caller,({'name-lead':'lead','name-known':'worker','name-id':'historical-id','name-missing-path':'worker/missing'} as any)[action],new AbortController().signal)
  else{Object.assign(row,{root:tree.rootOf(caller).id,names:tree.namesOf(caller),ancestors:tree.ancestryForChild(caller).ancestors});tree.assertAdmitting(caller)}
 }catch(error:any){row.error={code:error.code??null,message:error.message}}rows.push(row)
}
for(const action of ['normal','implicit-root','unnamed','missing-edge','cycle','inherited-identity','no-identity','no-parent','foreign-root','root-cold','delegated-root','unavailable','abort','missing-query']){
 const root=agent('root'),live=new Map([['root',root]]),trace:string[]=[],controller=new AbortController()
 const node=(id:string,parent?:string)=>({header:{id,...parent?{parentSession:parent}:{}},projections:{values:{subagent:parent?{seq:2}:null,subagentCatalog:[] as any[]}},inheritedEventCount:0})
 const nodes:any={root:node('root'),parent:node('parent','root'),child:node('child','parent')};nodes.root.projections.values.subagentCatalog=[{id:'parent',name:'worker'}];nodes.parent.projections.values.subagentCatalog=[{id:'child',name:'nested'}];let explicit:any=root
 if(action==='implicit-root')explicit=undefined;else if(action==='unnamed')delete nodes.root.projections.values.subagentCatalog[0].name
 else if(action==='missing-edge')nodes.parent.projections.values.subagentCatalog=[];else if(action==='cycle')nodes.parent.header.parentSession='child'
 else if(action==='inherited-identity')nodes.child.inheritedEventCount=3;else if(action==='no-identity')nodes.child.projections.values.subagent=null
 else if(action==='no-parent')delete nodes.child.header.parentSession;else if(action==='foreign-root')explicit=agent('other')
 else if(action==='root-cold'){explicit=undefined;live.clear()}else if(action==='delegated-root'){explicit=undefined;nodes.root.header.origin='subagent'}else if(action==='abort')controller.abort()
 const query={observeSession:async(id:string)=>{trace.push('read:'+id);if(action==='unavailable')throw Error('storage');return {...nodes[id],[Symbol.dispose](){trace.push('dispose:'+id)}}}}
 const ctx={agents:{get:(id:string)=>live.get(id)},get:()=>action==='missing-query'?undefined:query}
 const tree=Object.assign(Object.create(Manager.prototype),{ctx,host:{identityOf:()=>undefined},resident:new Map()}),row:any={kind:'ancestry',action}
 try{const value=await tree.resolveCreationAncestry(nodes.child,controller.signal,explicit);row.value={root:value.root.id,ancestors:value.ancestors,path:value.path??null}}
 catch(error:any){row.error={code:error.code??null,message:controller.signal.aborted?'aborted':error.message}}
 row.trace=trace;rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
