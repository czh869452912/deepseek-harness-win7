import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const root=path.resolve(process.argv[2]!),input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const {Client}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')).href)
const {StdioClientTransport}=await import(pathToFileURL(require.resolve('@modelcontextprotocol/client/stdio').replace(/\.cjs$/,'.mjs')).href)
const rows=[]
for(const mode of ['legacy','modern','closed','timeout','hold']){
 const log=path.join(input.output,'source-'+mode+'.jsonl'),transport=new StdioClientTransport({command:input.python,args:[input.peer,log,mode],stderr:'ignore'})
 const client=new Client({name:'dsh-mcp-client',version:'0.0.1'},{capabilities:{},versionNegotiation:{mode:'auto',probe:{timeoutMs:mode==='timeout'?1000:2000}}})
 let value:any
 const connecting=client.connect(transport)
 try{
  if(mode==='hold'){
   for(let i=0;i<1000;i++){
    if(fs.existsSync(log)&&fs.readFileSync(log,'utf8').includes('server/discover'))break
    await new Promise(resolve=>setTimeout(resolve,5))
   }
   await transport.close()
  }
  await connecting
  value={serverInfo:client.getServerVersion(),capabilities:client.getServerCapabilities(),instructions:client.getInstructions(),tools:await client.listTools()}
 }catch(error:any){value={error:{name:error.name,code:error.code,message:error.message}}}
 finally{await client.close();await transport.close()}
 const events=fs.readFileSync(log,'utf8').trim().split('\n').map(line=>JSON.parse(line)),starts=events.filter(row=>row.event==='start')
 const closed=starts.every(row=>{try{process.kill(row.pid,0);return false}catch{return true}})
 rows.push({mode,value,starts:starts.length,previousAlive:starts.map(row=>row.previousAlive),allClosed:closed,requests:events.filter(row=>row.event==='packet').map(row=>row.packet)})
}
process.stdout.write(JSON.stringify(rows))
