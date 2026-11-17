import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
const root=path.resolve(process.argv[2]!),cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
const output=[]
for(const fixture of cases){
 const client=new Client({name:'dsh-mcp-client',version:'0.0.1'}),requests:any[]=[],rows:any[]=[];client._serverCapabilities={tools:{}}
 let current:any
 client.request=async(packet:any)=>{requests.push(packet);if(packet.method==='tools/list')return {tools:[{name:'probe',inputSchema:{type:'object'},outputSchema:fixture.schema},{name:'good',inputSchema:{type:'object'},outputSchema:{}}]};return current}
 if('schema' in fixture)await client.listTools()
 for(const action of fixture.actions){
  if(action.notify){client._onnotification({jsonrpc:'2.0',method:'notifications/tools/list_changed'},{});continue}
  current=action.result
  const options='override' in action?{toolDefinition:{name:'probe',inputSchema:{type:'object'},outputSchema:action.override}}:undefined
  try{rows.push({value:await client.callTool({name:action.tool??'probe'},options)})}
  catch(error:any){rows.push({error:{name:error.name,message:error.message,...error.code!==undefined?{code:error.code}:{},...error.data!==undefined?{data:error.data}:{}}})}
 }
 output.push({name:fixture.name,rows,requests})
}
process.stdout.write(JSON.stringify(output))
