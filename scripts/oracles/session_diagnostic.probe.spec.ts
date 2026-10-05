import {it} from 'vitest'
import {Session} from '@deepseek-ai/dsh-session'
import {writeFileSync} from 'node:fs'
import {execFileSync} from 'node:child_process'

it('observes actual public Session create and restore admission diagnostics',()=>{
  const pin='cd5ef8148158c3a752a658978873241fdf8e2bbc'
  if(process.version!=='v22.22.2'||execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim()!==pin
    ||execFileSync('git',['-C','reference','status','--porcelain'],{encoding:'utf8'}).trim())throw new Error('Pinned clean Source required')
  const values=[['missing',undefined],['null',null],['true',true],['false',false],['zero',0],['one',1],
    ['fraction',1.5],['negative-zero',-0],['nan',NaN],['infinite',Infinity],['negative-infinite',-Infinity],
    ['empty-array',[]],['string','s'],['object',{}],['nested-array',['x',null,['y']]],
    ['large-exponent',1e21],['small-exponent',1e-7],['decimal-threshold',1e-6],['integer-threshold',1e20]] as const
  const rows:any[]=[]
  for(const mode of ['create','restore'])for(const field of ['version','id'])for(const [label,value] of values){
    const header:any={id:'s',version:0,createdAt:1}
    if(label==='missing')delete header[field]
    else header[field]=value
    const row:any={name:mode+'/'+field+'/'+label}
    try{
      if(mode==='create')Session.create('s' as any,[],header)
      else Session.fromRestore('s' as any,[],header)
      row.accepted=true
    }catch(error:any){row.error={name:error.name,message:error.message};row.accepted=false}
    rows.push(row)
  }
  writeFileSync(process.env.DSH_SESSION_DIAGNOSTIC_SOURCE_OUTPUT!,JSON.stringify({sourceCommit:pin,node:process.version,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
})
