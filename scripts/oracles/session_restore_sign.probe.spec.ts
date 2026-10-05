import {it} from 'vitest'
import {Session} from '@deepseek-ai/dsh-session'
import {writeFileSync} from 'node:fs'
import {execFileSync} from 'node:child_process'

it('observes signed numeric values through actual public Session restore',()=>{
  const pin='cd5ef8148158c3a752a658978873241fdf8e2bbc'
  if(process.version!=='v22.22.2'||execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim()!==pin
    ||execFileSync('git',['-C','reference','status','--porcelain'],{encoding:'utf8'}).trim())throw new Error('Pinned clean Source required')
  const rows:any[]=[]
  for(const field of ['version','createdAt','seedLength','delegationDepth','seq','time']){
    for(const [label,value] of [['whole',field==='version'||field==='seq'?0:1],['negative-zero',-0],['fraction',0.5]] as const){
      const header:any={id:'s',version:0,createdAt:1}
      const event:any={type:'session/end-seed',seq:0,time:1,data:{}}
      if(field==='seq'||field==='time')event[field]=value
      else header[field]=value
      const row:any={name:field+'/'+label}
      try{
        const session=Session.fromRestore('s' as any,[event],header)
        const actual=field==='seq'||field==='time'?session.events[0][field]:session.header[field]
        row.accepted=true
        row.safeInteger=Number.isSafeInteger(actual)
        row.negativeZero=Object.is(actual,-0)
        row.equalInput=Object.is(actual,value)
      }catch(error:any){row.error={name:error.name,message:error.message};row.accepted=false}
      rows.push(row)
    }
  }
  writeFileSync(process.env.DSH_RESTORE_SIGN_SOURCE_OUTPUT!,JSON.stringify({sourceCommit:pin,node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
