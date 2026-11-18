import {writeFileSync} from 'node:fs'
import {execFileSync} from 'node:child_process'
import {expect,it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import * as Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import {readFile} from 'node:fs/promises'
import {basename} from 'node:path'

it('observes complete original JSONL readers beside an owned Windows shared holder',async()=>{
  const pin='38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
  expect(process.version).toBe('v24.9.0')
  expect(execFileSync('git',['-C','reference','rev-parse','HEAD'],{encoding:'utf8'}).trim()).toBe(pin)
  expect(execFileSync('git',['-C','reference','status','--porcelain'],{encoding:'utf8'}).trim()).toBe('')
  const ctx=new Context()
  try{
    await ctx.plugin(SessionStore)
    await ctx.plugin(Jsonl,{root:process.env.DSH_JSONL_SHARING_ROOT!,compression:process.env.DSH_JSONL_SHARING_COMPRESSION! as 'none'|'zstd'})
    const provider=ctx.sessionPersistence
    const listed=await provider.list()
    const handle=await provider.open('sharing-session' as any,'read')
    const inspected={header:handle.header,inheritedEventCount:handle.inheritedEventCount,...await handle.read()}
    await handle.close()
    const path=process.env.DSH_JSONL_SHARING_FILE!
    const raw={filename:basename(path),content:(await readFile(path)).toString('base64')}
    expect(listed.map(value=>value.header.id)).toEqual(['sharing-session'])
    expect(inspected.events.map(value=>value.type)).toEqual(['session/end-seed'])
    expect(raw.content.length).toBeGreaterThan(0)
    writeFileSync(process.env.DSH_JSONL_SHARING_SOURCE_OUTPUT!,JSON.stringify({sourceCommit:pin,node:process.version,name:process.env.DSH_JSONL_SHARING_NAME,observed:{listed,inspected,raw}},null,2)+'\n',{encoding:'utf8',flag:'wx'})
  }finally{await ctx.fiber.dispose()}
})
