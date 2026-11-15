import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const {jsonSchemaToPy,renderToolsSdkPy}=await import(pathToFileURL(resolve(process.argv[2]!, 'packages/core/tool-executor-ptc/src/py-types.ts')).href)
const data=JSON.parse(readFileSync(process.argv[3]!, 'utf8'))
process.stdout.write(JSON.stringify([...data.scalars.map((schema:unknown)=>({kind:'scalar',value:jsonSchemaToPy(schema)})), ...data.sets.map((schemas:any[])=>({kind:'sdk',value:renderToolsSdkPy(schemas)}))]))
