import fs from 'node:fs'
import path from 'node:path'
import {createRequire} from 'node:module'
import {createHash} from 'node:crypto'
import {pathToFileURL} from 'node:url'
import {execFileSync} from 'node:child_process'
const root=path.resolve(process.argv[2]),require=createRequire(path.join(root,'packages/mcp/mcp-client/package.json'))
if(execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!=='38a6a5c965aa99ab525161efb7cc5cf1fe62fced')throw Error('Expected fixed Source')
const ts=createRequire(path.join(root,'package.json'))('typescript')
const entry=require.resolve('@modelcontextprotocol/client').replace(/\.cjs$/,'.mjs')
if(JSON.parse(fs.readFileSync(path.resolve(entry,'../../package.json'),'utf8')).version!=='2.2.0')throw Error('Expected pinned client SDK 2.2.0')
const text=fs.readFileSync(entry,'utf8'),ast=ts.createSourceFile(entry,text,ts.ScriptTarget.Latest,true)
let declaration
for(const node of ast.statements){
 if(!ts.isImportDeclaration(node)||!node.importClause?.namedBindings?.elements)continue
 for(const item of node.importClause.namedBindings.elements)if(item.name.text==='specTypeSchemas')declaration=node
}
if(!declaration)throw Error('SDK schema import not found')
const file=path.resolve(path.dirname(entry),declaration.moduleSpecifier.text)
// Export the unchanged private 2025 codec schema factory in a temporary sibling
// module so all its original imports resolve in the exact SDK installation.
const temporary=path.join(path.dirname(file),'.rc022-resource-schemas-'+process.pid+'.mjs')
const original=fs.readFileSync(file,'utf8');let source,created=false
try{
 fs.writeFileSync(temporary,original+'\nexport {buildSchemas2025 as rc022Schemas};\n',{flag:'wx'})
 created=true
 source=(await import(pathToFileURL(temporary).href)).rc022Schemas()
}finally{if(created)fs.unlinkSync(temporary)}
const kinds=new Set()
function capture(schema){
 const def=schema._zod?.def
 if(!def)throw Error('Expected a pinned Zod schema')
 kinds.add(def.type);const node={type:def.type}
 switch(def.type){
  case 'object':node.shape=Object.fromEntries(Object.entries(def.shape).map(([key,value])=>[key,capture(value)]));if(def.catchall)node.catchall=capture(def.catchall);break
  case 'optional':case 'nullable':node.inner=capture(def.innerType);break
  case 'array':node.element=capture(def.element);break
  case 'record':node.key=capture(def.keyType);node.value=capture(def.valueType);break
  case 'union':node.options=def.options.map(capture);break
  case 'intersection':node.left=capture(def.left);node.right=capture(def.right);break
  case 'literal':node.values=def.values;break
  case 'enum':node.values=Object.values(def.entries);break
  case 'number':if(def.format)node.format=def.format;node.checks=(def.checks??[]).map(check=>check._zod.def);break
  case 'unknown':case 'string':case 'boolean':case 'never':break
  default:throw Error('Unreviewed schema kind: '+def.type)
 }
 return node
}
const names=['ListResourcesResultSchema','ListResourceTemplatesResultSchema','ReadResourceResultSchema']
const schemas=Object.fromEntries(names.map(name=>[name,capture(source[name])]))
fs.writeFileSync(process.argv[3],JSON.stringify({upstream:'38a6a5c965aa99ab525161efb7cc5cf1fe62fced',sdkVersion:'2.2.0',wireEra:'2025-11-25',schemaSourceSha256:createHash('sha256').update(fs.readFileSync(file)).digest('hex'),kinds:[...kinds].sort(),schemas},null,2)+'\n')
