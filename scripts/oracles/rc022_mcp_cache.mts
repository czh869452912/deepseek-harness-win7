import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
const root=path.resolve(process.argv[2]!),cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
const clone=(value:any)=>JSON.parse(JSON.stringify(value)),output=[]
for(const fixture of cases){
 const client=new Client({name:'dsh-mcp-client',version:'0.0.1'},{defaultCacheTtlMs:fixture.defaultTtl??0,listMaxPages:fixture.maxPages??64})
 client._serverCapabilities={tools:{},resources:{}};let clock=0,count=0,ttl=fixture.ttl??100,last:any;client._cache.now=()=>clock
 const requests:any[]=[],rows:any[]=[]
 const notify=(packet:any)=>client._onnotification({jsonrpc:'2.0',...packet},{})
 client.request=async(packet:any)=>{
  requests.push(clone(packet));count++
  if(count===fixture.invalidateAt)notify(fixture.notification)
  if(count===fixture.failAt)throw new Error('scripted page failure')
  const method=packet.method,params=packet.params??{},page=Number(params.cursor??0),result:any={ttlMs:ttl,cacheScope:'private'}
  if(method==='resources/read')result.contents=[{uri:params.uri,text:String(count)}]
  else{
   const key=({'tools/list':'tools','resources/list':'resources','resources/templates/list':'resourceTemplates'} as any)[method],item:any={name:'item'+count}
   if(key==='tools')item.inputSchema={type:'object'};else if(key==='resources')item.uri='doc://'+count;else item.uriTemplate='doc://{'+count+'}'
   result[key]=[item];if(page+1<(fixture.pages??1))result.nextCursor=String(page+1)
  }
  return result
 }
 for(const entry of fixture.actions){
  const verb=entry.verb
  if(verb==='advance'){clock+=entry.ms;continue}
  if(verb==='setTtl'){ttl=entry.value;continue}
  if(verb==='notify'){const {verb,...packet}=entry;notify(packet);continue}
  if(verb==='mutate'){last.ttlMs=-1;const key=['tools','resources','resourceTemplates','contents'].find(key=>key in last)!;last[key][0].name='mutated';continue}
  const params=entry.params??(verb==='readResource'?{uri:'doc://a'}:undefined)
  try{last=await client[verb](params,entry.options);rows.push({value:clone(last)})}
  catch(error:any){rows.push({error:{name:error.name,message:error.message,...error.code!==undefined?{code:error.code}:{},...error.data!==undefined?{data:error.data}:{}}})}
 }
 output.push({name:fixture.name,rows,requests})
}
process.stdout.write(JSON.stringify(output))
