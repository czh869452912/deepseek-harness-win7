import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client,StreamableHTTPClientTransport}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
function normalize(value:any):any{
 if(value instanceof Error)return {name:value.name,message:value.message,...'code'in value?{code:value.code}:{},...'data'in value&&value.data!==undefined?{data:normalize(value.data)}:{}}
 if(Array.isArray(value))return value.map(normalize)
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([,v])=>v!==undefined).map(([k,v])=>[k,normalize(v)]))
 return value
}
const rows=[]
for(const mode of input.modes){
 const transport=new StreamableHTTPClientTransport(new URL(input.url+'/source/'+mode),{requestInit:{headers:input.headers}})
 const client=new Client({name:'dsh-mcp-client',version:'0.0.1'},{capabilities:{},versionNegotiation:{mode:'auto',probe:{timeoutMs:mode==='timeout'?50:2000}}})
 const connecting=client.connect(transport);let value
 try{
  if(mode==='hold'){
   for(let i=0;i<1000;i++){
    if(fs.existsSync(input.log)&&fs.readFileSync(input.log,'utf8').split('\n').filter(Boolean).some(line=>{const row=JSON.parse(line);return row.path==='/source/hold'&&row.packet?.method==='server/discover'}))break
    await new Promise(resolve=>setTimeout(resolve,5))
   }
   await transport.close()
  }
  await connecting
  value={serverInfo:client.getServerVersion(),capabilities:client.getServerCapabilities(),instructions:client.getInstructions(),tools:await client.listTools(),resource:await client.readResource({uri:'doc://文档/one'}),sessionId:transport.sessionId??null}
 }catch(error){value={error:normalize(error)}}
 finally{await client.close();await transport.close()}
 const requests=fs.readFileSync(input.log,'utf8').trim().split('\n').map(line=>JSON.parse(line)).filter(row=>row.path==='/source/'+mode&&row.httpMethod==='POST').map(row=>({packet:row.packet,headers:Object.fromEntries(Object.entries(row.headers).map(([k,v])=>[k.toLowerCase(),v]).filter(([k])=>['content-type','accept','authorization'].includes(k as string)||(k as string).startsWith('mcp-')))}))
 rows.push({mode,value,requests})
}
process.stdout.write(JSON.stringify(rows))
