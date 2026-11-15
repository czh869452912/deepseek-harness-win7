import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {parsePatch,applyHunks}=await load('packages/fs/fs-patch/src/index.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8'))
console.log(JSON.stringify(cases.map((value:any,index:number)=>{try{return {index,kind:value.kind,value:value.kind==='parse'?parsePatch(value.patch):applyHunks(value.before,value.hunks)}}catch(error:any){return {index,kind:value.kind,error:{name:error.name,lineNumber:error.lineNumber,reason:error.reason,message:error.message}}}})))
