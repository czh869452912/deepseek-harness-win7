import {execFileSync} from 'node:child_process'
import {readFileSync,writeFileSync} from 'node:fs'
import {MessageChannel} from 'node:worker_threads'
import {expect,it} from 'vitest'
import {runWorkerSession} from '../../reference/packages/workflow/workflow-worker-thread/src/session.ts'

it('captures complete current Source worker session engine boundaries',async()=>{
  const cases=JSON.parse(readFileSync(new URL('./js-error-fixtures.json',import.meta.url),'utf8'))["errors"]
  expect(cases).toHaveLength(10)
  const rows=[]
  for(const scenario of cases){
    const channel=new MessageChannel()
    const events:any[]=[]
    let readyResolved=false
    let resolveResult:(value:any)=>void=()=>{}
    const result=new Promise<any>(resolve=>{resolveResult=resolve})
    channel.port1.on('message',message=>{
      if(message.type==='ready'){readyResolved=true;channel.port1.postMessage({type:'go'})}
      else{events.push(message);if(message.type==='result')resolveResult(message.result)}
    })
    try{
      const running=runWorkerSession(channel.port2,{meta:{name:scenario.name,description:'engine research'},body:scenario.body,args:{nested:{value:2}},limits:{maxConcurrentAgents:2,maxTotalAgents:10,maxItemsPerCall:30,syncTimeoutMs:200}})
      const value=await result
      await running
      rows.push({name:scenario.name,body:scenario.body,readyResolved,events,result:value,negativeZero:scenario.name==='scalars'&&Object.is(value.value[5],-0)})
    }finally{channel.port1.close();channel.port2.close()}
  }
  writeFileSync(process.env.DSH_JS_ERRORS_ERRORS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
