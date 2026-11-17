import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client,StreamableHTTPClientTransport}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
const records=()=>fs.readFileSync(input.log,'utf8').split('\n').filter(Boolean).map(line=>JSON.parse(line)),output=[]
for(const [index,fixture] of input.cases.entries()){
 const urlPath='/source/header/'+index+'/'+fixture.mode,client=new Client({name:'dsh-mcp-client',version:'0.0.1'},{capabilities:{},versionNegotiation:{mode:'auto'}}),transport=new StreamableHTTPClientTransport(new URL(input.url+urlPath),{requestInit:{headers:{Authorization:'Bearer owned'}}}),errors:any[]=[]
 client.onerror=(error:any)=>errors.push({name:error.name,message:error.message,code:error.code??null})
 let listing,result
 try{
  await client.connect(transport);listing=await client.listTools(fixture.cursor?{cursor:'explicit'}:undefined)
  try{result={value:await client.callTool({name:'probe',arguments:{trace:fixture.value}},fixture.options)}}
  catch(error:any){result={error:{name:error.name,message:error.message,...error.code!==undefined?{code:error.code}:{},...error.data!==undefined?{data:error.data}:{}}}}
 }finally{await client.close();await transport.close()}
 const wire=records().filter(row=>row.path===urlPath&&['tools/list','tools/call'].includes(row.packet.method)).map(row=>({packet:row.packet,headers:Object.fromEntries(Object.entries(row.headers).filter(([key])=>key.startsWith('mcp-')||['authorization','content-type','x-extra','accept'].includes(key)))}))
 output.push({case:fixture,tools:listing.tools.map((tool:any)=>tool.name),result,errors,wire})
}
process.stdout.write(JSON.stringify(output))
