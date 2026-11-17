import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
const root=path.resolve(process.argv[2]!),cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
const require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
const entry=require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs'),text=fs.readFileSync(entry,'utf8'),match=text.match(/from "\.\/(src-[^"]+\.mjs)"/)
if(!match)throw Error('SDK pure module not found')
const {E:scanXMcpHeaderDeclarations,w:buildMcpParamHeaders}=await import(pathToFileURL(path.join(path.dirname(entry),match[1])).href)
if(typeof scanXMcpHeaderDeclarations!=='function'||typeof buildMcpParamHeaders!=='function')throw Error('SDK exports differ')
process.stdout.write(JSON.stringify(cases.map((fixture:any)=>{const scan=scanXMcpHeaderDeclarations(fixture.schema);return {scan,...scan.valid?{headers:buildMcpParamHeaders(scan.declarations,fixture.args)}:{}}})))
