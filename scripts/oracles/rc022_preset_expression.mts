import {readFileSync} from 'node:fs'
import {pathToFileURL} from 'node:url'
import {load} from './rc022_subagent_fixture.mts'
const {evaluate}=await load('vendor/loader/src/config/utils.ts'),{workspace,expressions}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const expression of expressions){
 try{rows.push({value:evaluate({baseUrl:pathToFileURL(workspace).href+'/'},expression)})}
 catch(error:any){rows.push({code:error.code??error.name})}
}
console.log(JSON.stringify(rows))
