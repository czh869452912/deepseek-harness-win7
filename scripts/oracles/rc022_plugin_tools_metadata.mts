/** Export only original static tool schema/text and three refusal lookup tables. */
import fs from 'node:fs'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const source=process.argv[2]!,Tools=await load('packages/boot/plugin-manager/src/tools.ts')
let definition:any
Tools.apply({tools:{register:(value:any)=>{definition=value}}})
const imported=await load('node_modules/typescript/lib/typescript.js'),ts=imported.default??imported
const text=fs.readFileSync(path.join(source,'packages/boot/plugin-manager/src/tools.ts'),'utf8')
const ast=ts.createSourceFile('tools.ts',text,ts.ScriptTarget.Latest,true),tables:any={}
for(const statement of ast.statements){
 if(!ts.isVariableStatement(statement))continue
 for(const declaration of statement.declarationList.declarations){
  const name=declaration.name.getText(ast)
  if(!['ERROR_STEPS','FAILURE_STEPS','RESTART_STEPS'].includes(name))continue
  tables[name]=Object.fromEntries(declaration.initializer.properties.map((property:any)=>[property.name.text,property.initializer.text]))
 }
}
process.stdout.write(JSON.stringify({name:definition.name,description:definition.description,parameters:definition.parameters,output:{schema:definition.output.schema},...tables},null,2)+'\n')
