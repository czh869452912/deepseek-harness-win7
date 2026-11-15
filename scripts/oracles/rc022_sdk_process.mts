import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const run=await load('packages/subagent/subagent-dsh-sdk/src/run.ts'),api=await load('packages/sdk/client/src/api.ts'),rows:any[]=[],workspace=JSON.parse(readFileSync(process.argv[3]!,'utf8')),source=process.argv[2]!
const original=run.internals.createHarness,names=['RC022_SDK_TOKEN','DSH_RC022_SDK_FACT'],old=names.map(name=>process.env[name])
process.env.RC022_SDK_TOKEN='ambient';process.env.DSH_RC022_SDK_FACT='ambient'
try{for(const env of JSON.parse(readFileSync(process.argv[4]!,'utf8'))){
 const clients:any[]=[],reports:any[]=[]
 run.internals.createHarness=(options:any)=>{const runtime={command:process.execPath,args:[join(source,'packages/sdk/client/tests/fake-runtime.ts')],cwd:options.processCwd,environment:()=>options.env,description:'scripted SDK subagent runtime',initializeTimeoutMs:2000,requestTimeoutMs:2000,shutdownTimeoutMs:100,disposeEofGraceMs:100,disposeGraceMs:500},harness=api.createProcessDeepSeekHarness(runtime,options);clients.push(harness.client);return harness}
 const spec={profile:'sdk',patches:[],dshHome:join(workspace,'home'),cwd:join(workspace,'child'),originCwd:join(workspace,'origin'),provider:'script',model:'model',reasoningEffort:'low',maxTokens:17,env:{...env,FAKE_TEXT:'answer',RC022_SDK_TOKEN:'explicit'},shutdownTimeoutMs:100,disposeEofGraceMs:100,disposeGraceMs:500,onError:(error:any,reason:any)=>reports.push([error.name==='Error'?'RuntimeError':error.name,reason])}
 let value:any
 try{const handle=await run.startSdkRun({signal:new AbortController().signal,prompt:[{type:'text',text:'task'}]},spec);value={result:await handle.result};const first=handle.dispose();value.sameDisposal=first===handle.dispose();await first}
 catch(error:any){value={startFailure:{name:error.name==='Error'?'RuntimeError':error.name,message:error.message}}}
 value=JSON.parse(JSON.stringify(value).split(JSON.stringify(workspace).slice(1,-1)).join('$WORKSPACE'))
 rows.push({value,reports,reaped:clients.every(client=>client.child===undefined||client.child.exitCode!==null||client.child.signalCode!==null),pipesClosed:clients.every(client=>client.child===undefined||[client.child.stdin,client.child.stdout,client.child.stderr].every(stream=>stream.destroyed)),pending:clients.reduce((total,client)=>total+(client.transport?.pending?.size??0),0)})
}}finally{run.internals.createHarness=original;names.forEach((name,i)=>{if(old[i]===undefined)delete process.env[name];else process.env[name]=old[i]})}
process.stdout.write(JSON.stringify(rows))
