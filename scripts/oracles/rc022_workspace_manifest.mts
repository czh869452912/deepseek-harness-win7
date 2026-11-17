import fs from 'node:fs/promises'
import {load} from './rc022_subagent_fixture.mts'
const {parsePrimaryRuntime,workspaceDependencyPaths}=await load('packages/skill/tool-workspace-dependencies/src/index.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const entry of inputs){
 try{const value=parsePrimaryRuntime(structuredClone(entry.value));rows.push({value,...Object.hasOwn(entry,'root')?{paths:workspaceDependencyPaths(entry.root,value)}:{}})}
 catch(error:any){rows.push({error:error.message})}
}
console.log(JSON.stringify(rows))
