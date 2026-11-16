import fs from 'node:fs'
import path from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {parseNumstat}=await load('packages/deliverables/workspace-changes/src/numstat.ts')
const {canonicalPath,compareDisplay,displayPathOf,durablePathOf,isInside,temporaryRoots}=await load('packages/deliverables/workspace-changes/src/paths.ts')
const {captureFile,sameCapture}=await load('packages/deliverables/workspace-changes/src/capture.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows=[]
for(const text of input.numstats){
 let result
 try{result=parseNumstat(text)}catch(error:any){result={error:error.message}}
 rows.push({kind:'numstat',input:text,result})
}
for(const test of input.paths)rows.push({kind:'path',input:test,result:{inside:isInside(test.cwd,test.absolute),display:displayPathOf(test.absolute,test.cwd,test.root,test.home),path:durablePathOf(test.absolute,test.cwd)}})
const captures=[]
for(const [name,limit] of [['missing',10],['empty',0],['small',8],['small',7],['same',8],['binary',3],['boundary',8001],['probe-boundary',8000]]){
 let value=await captureFile(path.join(input.files,name),path.join(input.files,'source-copies'),limit)
 if(value?.file)value={...value,file:path.basename(value.file)}
 captures.push(value);rows.push({kind:'capture',name,limit,result:value})
}
rows.push({kind:'same',result:captures.map(a=>captures.map(b=>sameCapture(a,b)))})
rows.push({kind:'canonical',result:{missing:await canonicalPath(path.join(input.files,'missing','child')),roots:await temporaryRoots([input.files,path.join(input.files,'..','files')])}})
const names=['a','A','../x','~/','\u{10000}','\ue000','a\u{1f600}','a\ufffd']
rows.push({kind:'display-order',result:names.map(a=>names.map(b=>compareDisplay({display:a},{display:b})))})
process.stdout.write(JSON.stringify(rows))
