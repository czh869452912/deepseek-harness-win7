import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {parseInstallSpec,pinnedGitOrigin,dependencySpec}=await load('packages/boot/plugin-manager/src/install-spec.ts'),{classifyInstallFailure}=await load('packages/boot/plugin-manager/src/install-failure.ts'),data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
function result(operation:()=>unknown){try{return {value:operation()??null}}catch(error:any){return {error:{name:error.name,message:error.message,...error.spec===undefined?{}:{spec:error.spec},...error.reason===undefined?{}:{reason:error.reason}}}}}
for(const spec of data.specs)rows.push({kind:'spec',input:spec,parsed:result(()=>parseInstallSpec(spec)),origin:result(()=>pinnedGitOrigin(spec))})
for(const item of data.dependencies)rows.push({kind:'dependency',input:item,value:dependencySpec(item.name,item.recorded,item.profile,item.packageName)})
for(const item of data.failures)rows.push({kind:'failure',input:item,value:classifyInstallFailure(item)})
console.log(JSON.stringify(rows))
