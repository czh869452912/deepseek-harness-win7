import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const {jsonSchemaToTs,renderToolsSdk}=await import(pathToFileURL(resolve(process.argv[2]!, 'packages/core/tool-executor-ptc/src/ts-types.ts')).href)
const data=JSON.parse(readFileSync(process.argv[3]!, 'utf8'))
process.stdout.write(JSON.stringify([...data.scalars.map((schema:unknown)=>({kind:'scalar',value:jsonSchemaToTs(schema)})), ...['function-body','repl','script'].flatMap(format=>data.sets.map((schemas:any[])=>({kind:format,value:renderToolsSdk(schemas,format)})))]))
