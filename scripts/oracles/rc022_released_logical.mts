import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const source=process.argv[2]!, corpus=process.argv[3]!
const load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const released=await load('packages/session/session-format-v0-to-v1/src/index.ts')
const validation=await load('packages/session/session-format-v0-to-v1/src/validation.ts')
const restore=await load('packages/session/session-format-v0-to-v1/src/testing/restore.ts')
function decode(value:any):any {
  if(value && !Array.isArray(value) && typeof value==='object') {
    if(Object.keys(value).length===1 && '$scalar' in value)
      return ({undefined,'-0':-0,NaN,Infinity} as any)[value.$scalar]
    return Object.fromEntries(Object.entries(value).map(([key,child])=>[key,decode(child)]))
  }
  return Array.isArray(value)?value.map(decode):value
}
function execute(test:any):any {
  if(test.kind!=='released-logical')throw new Error('Unexpected corpus kind')
  switch(test.operation) {
    case 'semantics': released.assertReleasedPayloadSemantics(decode(test.event),test.version);break
    case 'payload': released.assertReleasedEventPayload(decode(test.event),test.version);break
    case 'relationships': released.assertReleasedArtifactRelationships(decode(test.artifact),test.extensions);break
    case 'surface-metadata': released.assertReleasedSurfaceMetadata(decode(test.event),test.event.seq,test.event.type,test.assistantSources??'allow-empty-assistant');break
    case 'header': validation.assertReleasedSessionFormatHeader(decode(test.header),test.version);break
    case 'coordinates': validation.assertReleasedArtifactCoordinates(decode(test.artifact),test.allowLegacy??false,test.known?new Set(test.known):undefined,test.neutral??false,test.frozen??false);break
    case 'restore-v0': return restore.restoreV0ToV1(decode(test.header),decode(test.rows),test.recovery??'strict')
    case 'restore-v1': return restore.restoreV1(decode(test.header),decode(test.rows),test.recovery??'strict')
    default:throw new Error('Unknown logical operation: '+test.operation)
  }
  return null
}
const rows=JSON.parse(readFileSync(corpus,'utf8')).map((test:any)=>{
  try{return {case:test.case,outcome:'value',value:execute(test)}}
  catch(error:any){return {case:test.case,outcome:'error',name:error.name,message:error.message,
    ...(error.cause===undefined?{}:{cause:error.cause instanceof Error?error.cause.message:String(error.cause)})}}
})
process.stdout.write(JSON.stringify(rows))
