import {load} from './rc022_subagent_fixture.mts'
const {Remote,RemoteScope,remoteMethods,principalOf}=await load('packages/typert/protocol/src/index.ts'),rows:any[]=[],readers:any={session:(request:any)=>request.sessions}
class Marked{
 @Remote plain(request:any){void request}
 @Remote({name:'watch',mode:'stream',resources:readers}) observe(request:any){void request}
 @RemoteScope('agent',{name:'write',resources:{session:(identity:any)=>identity}}) scoped(identity:any){void identity}
}
readers.session=()=> 'mutated';const service=new Marked()
for(const marker of remoteMethods(service)){
 const {resources,...value}=marker
 if(resources){value.read=resources.session(marker.method==='observe'?{sessions:['a','b']}:'scope');try{resources.session=()=> 'mutated';value.frozen=false}catch{value.frozen=true}}
 rows.push(value)
}
const snapshot=remoteMethods(service);snapshot[0].method='changed'
rows.push({snapshotSafe:remoteMethods(service)[0].method==='plain'})
for(const scoped of [false,true])for(const option of [{},{unknown:true},{mode:'unary'},{resources:{}},{resources:{session:7}}]){
 try{scoped?RemoteScope('agent',option):Remote(option)}catch(error:any){rows.push({scoped,error:error.message})}
}
class Base{@Remote({resources:{session:(value:any)=>value}}) inherited(value:any){void value}}
class Child extends Base{@Remote('another') child(value:any){void value}}
rows.push({inherited:remoteMethods(new Child()).map((marker:any)=>marker.method)})
for(const value of [undefined,{peer:{principal:{kind:'owner'}}},{peer:{principal:{kind:'guest',id:'g'}}},{peer:{principal:{kind:'Owner'}}}])rows.push({principal:principalOf(value)??null})
process.stdout.write(JSON.stringify(rows))
