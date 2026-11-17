import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {DomainImpl}=await load('packages/storage/storage-domain/src/domain.ts'),{StorageError}=await load('packages/storage/storage/src/error.ts')
const cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const entry of cases){
 const calls:any[]=[],events:any[]=[],warnings:any[]=[],closed:any[]=[],medium=new Map<string,unknown>([['a',1],['b',2],['c',3]])
 const failure=new StorageError(entry.failure==='unknown-state'?'unknown-state':'malformed-medium','refused')
 let release!:()=>void,entered!:()=>void,domain:any
 const gate=new Promise<void>(resolve=>release=resolve),began=new Promise<void>(resolve=>entered=resolve)
 const unit={
  async putRecord(table:any,key:any,value:any){calls.push(['put',key,value]);medium.set(key,value)},
  async deleteRecords(table:any,keys:any){
   calls.push(['batch',[...keys]]);entered();if(entry.queued)await gate
   if(entry.failure==='normal')throw failure
   if(entry.failure==='unknown-state'){medium.delete(keys[0]);throw failure}
   for(const key of keys)medium.delete(key)
  },
  async setGlobal(value:any){calls.push(['global',value])},async close(){closed.push('unit')},
 }
 const ctx={logger:{warn(){warnings.push(true)}},emit(event:any,change:any){
  events.push({key:change.key,operation:change.operation,view:Object.fromEntries(domain.table('t').entries())})
  if(entry.throwObserver)throw new Error('observer failed')
 }}
 domain=new DomainImpl(ctx,{name:'shape',version:1,tables:{t:{}},global:{initial:0}},unit,new Map([['t',new Map(medium)]]),0,()=>closed.push('domain'))
 const table=domain.table('t')
 const result=async(promise:any)=>{try{const value=await promise;return {value:value===undefined?null:value}}catch(error:any){return {error:{code:error.code??null,same:error===failure}}}}
 let deleted,following
 if(entry.queued){
  await table.put('queued',4);const deletion=result(table.deleteMany(entry.keys));await began
  const after=result(table.put('after',5));release();[deleted,following]=await Promise.all([deletion,after])
 }else{deleted=await result(table.deleteMany(entry.keys));following=await result(table.put('after',5))}
 const reads:any={}
 for(const [name,read] of Object.entries({get:()=>table.get('b'),entries:()=>Object.fromEntries(table.entries()),keys:()=>[...table.keys()],size:()=>table.size,global:()=>domain.global.get()})){
  try{reads[name]={value:read()}}catch(error:any){reads[name]={error:{code:error.code??null,same:error===failure}}}
 }
 await domain.close();await domain.close();let afterClose
 try{table.get('b')}catch(error:any){afterClose=error.code??null}
 rows.push({case:entry,deleted,following,calls,events,warnings:warnings.length,reads,medium:Object.fromEntries(medium),closed,afterClose})
}
console.log(JSON.stringify(rows))
