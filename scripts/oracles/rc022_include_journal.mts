/** Observe original Include journal/patch modules without rewriting them. */
import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!
const j=await import(pathToFileURL(resolve(root,'vendor/include/src/journal.ts')).href)
const p=await import(pathToFileURL(resolve(root,'vendor/include/src/patch.ts')).href)
function decode(value:any):any{
  if(value&&typeof value==='object'&&!Array.isArray(value)&&value.$undefined===true&&Object.keys(value).length===1)return undefined
  if(Array.isArray(value))return value.map(decode)
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,decode(v)]))
  return value
}
function encode(value:any):any{
  if(value===undefined)return {$undefined:true}
  if(Array.isArray(value))return value.map(encode)
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,encode(v)]))
  return value
}
function observe(raw:any):any{
  const c=decode(raw),warnings:any[]=[],warn=(...args:any[])=>warnings.push(args)
  if(c.op==='merge')return encode(j.mergeRecords(c.older??undefined,c.newer)??null)
  if(c.op==='diff')return encode(j.diffOptions(c.older,c.newer))
  const journal=new Map<string,any>(Object.entries(c.journal??{}))
  if(c.op==='apply')return encode([j.applyJournal(c.data,journal,(id:string,key:string|null)=>!c.filtered||(id!=='b'&&key!=='config'),warn),warnings])
  if(c.op==='route'){
    const changed=p.routeJournal(journal,c.data,c.patches,warn)
    return encode([c.data,c.patches,changed,warnings])
  }
  if(c.op==='reconcile'){
    const index=new p.PatchIndex(c.patches),conflicts=j.reconcile(journal,j.flatten(c.base),j.flatten(c.theirs),(id:string,key:string|null)=>index.fileOwned(id,key))
    return encode([Object.fromEntries(journal),conflicts])
  }
  if(c.op==='record'){
    const result=new Map(),change={id:'a',options:c.options,legacy:c.legacy??undefined,group:{data:[{},c.options]},...(c.moved?{from:{}}:{})}
    j.record(result,change as any,'g');return encode(Object.fromEntries(result))
  }
  const index=new p.PatchIndex(c.patches),owner=(value:any)=>Object.fromEntries(Object.entries(value).filter(([key])=>!['list','options'].includes(key)))
  return c.ids.map((id:string)=>[id,owner(index.entry(id)),c.keys.map((key:string)=>[key,owner(index.key(id,key)),index.fileOwned(id,key)])])
}
process.stdout.write(JSON.stringify(JSON.parse(readFileSync(process.argv[3]!,'utf8')).map(observe)))
