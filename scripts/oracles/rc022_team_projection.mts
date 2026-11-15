import {resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
import {readFileSync} from 'node:fs'
const load=(path:string)=>import(pathToFileURL(resolve(process.argv[2]!,path)).href)
const {teamProjectionDefinition:TEAM,emptyTeamState,teamProjectionView}=await load('packages/team/agent-team/src/projection.ts'),{writeScope,requiredText}=await load('packages/team/agent-team/src/validation.ts'),rows:any[]=[]
for(const input of JSON.parse(readFileSync(process.argv[3]!,'utf8'))){
 const row:any={kind:input.kind,name:input.name??input.value}
 try{
  if(input.kind==='project'){
   let state=emptyTeamState('root',input.cut);const steps:any[]=[]
   for(const [seq,data] of input.events.entries()){
    const prior=state;state=TEAM.apply(state,{...data,seq,time:seq});const view=teamProjectionView(state)
    steps.push({state,view,sameState:state===prior,sameTasks:state.tasks===prior.tasks,sameView:view===teamProjectionView(state)})
   }Object.assign(row,{state,view:teamProjectionView(state),steps})
  }else if(input.kind==='scope')row.value=writeScope(input.value)
  else if(input.kind==='text')row.value=requiredText(input.value,'subject',input.limit)
  else row.accepted=TEAM.stateSchema.safeParse(input.value).success
 }catch(error:any){row.error={code:error.code,message:error.message}}
 rows.push(row)
}
process.stdout.write(JSON.stringify(rows))
