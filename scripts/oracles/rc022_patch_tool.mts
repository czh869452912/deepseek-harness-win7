import {observations} from './rc022_patch_execution.mts'
import {definitions} from './rc022_patch_definition.mts'
import {load} from './rc022_subagent_fixture.mts'
import {readFileSync} from 'node:fs'
const output=await load('packages/fs/tool-fs/src/apply-patch-output.ts'),presentation=await load('packages/fs/tool-fs/src/apply-patch-presentation.ts'),input=JSON.parse(readFileSync(process.argv[3]!,'utf8'))
const rows=observations.filter((row:any)=>!('thrown' in row.report)).map((row:any)=>{try{const value=output.patchToolValue(row.report),meta=output.patchPresentationMeta(value);return {name:row.name,value,render:output.renderPatch(value),meta,presentation:presentation.presentPatchResult({isError:false,meta})??null}}catch(error:any){return {name:row.name,error:{name:error.name,code:error.code??null,message:error.message}}}})
rows.push(...input.cases.map((item:any)=>({name:'preview-'+item.name,value:presentation.presentPatchCall(item.patch)??null})))
for(const meta of [null,{}, {diffs:[]},{diffs:[{path:'a',oldText:null,newText:'new'}]},{diffs:[{path:'a',oldText:'old',newText:'new'}],stopped:true},{diffs:[{path:'a',oldText:'old',newText:'new'}],stopped:1},{diffs:[{path:'a',newText:'new'}]},{diffs:[{path:'a',oldText:1,newText:'new'}]}])rows.push({name:'replay',meta,value:presentation.presentPatchResult({isError:false,meta})??null,error:presentation.presentPatchResult({isError:true,meta})??null})
rows.push({name:'definitions',value:await definitions()});console.log(JSON.stringify(rows))
