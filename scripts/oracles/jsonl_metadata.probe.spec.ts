import {it} from 'vitest'
import {createHash} from 'node:crypto'
import {readFileSync,writeFileSync,existsSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join,dirname} from 'node:path'
import {Context} from '@deepseek-ai/cordis'
import Sessions from '@deepseek-ai/dsh-session'
import Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'
import {parseHeaderMeta,scanLog} from '../../reference/packages/session/session-persistence-jsonl/src/format.ts'
import {compressZstdFrame} from '../../reference/packages/session/session-persistence-jsonl/src/zstd.ts'

const base = {type:'session',id:'raw',version:0,createdAt:1,delegationDepth:0}
const operations = ['stored','raw','list','suffix','inspect']
const sha = (bytes:Buffer) => createHash('sha256').update(bytes).digest('hex')
function formatObserved(operation: () => unknown) {
  try {return {value:operation() ?? null}} catch(error:any) {return {error:{name:error.name,message:error.message}}}
}
async function observed(operation: () => any,root:string) {
  try {
    const value = await operation()
    if (value && 'revision' in value) delete value.revision
    return JSON.parse(JSON.stringify({value:value ?? null}).replaceAll(root.replaceAll('\\','\\\\'),'<root>'))
  } catch(error:any) {
    return {error:{name:error.name,message:error.message.replaceAll(root,'<root>'),
      ...error.location === undefined ? {} : {location:{...error.location,path:error.location.path.replaceAll(root,'<root>')}}}}
  }
}

it('observes actual malformed header and both physical encodings without mutation',async () => {
  const directory = process.env.JSONL_PROVIDER_DIRECTORY!
  const inputs:any[] = [],rows:any[] = []
  const cases: [string, string][] = [['base',JSON.stringify(base)]]
  for (const [field, values] of Object.entries({cwd:[null,false,1,[],{},''],parentSession:[null,false,1,[]],seedLength:[null,false,1.5,-1],
      origin:[null,'',false],agentPreset:[null,{},1],createdAt:[-1,0.5,9007199254740992,null],delegationDepth:[-1,0.5,null],
      version:[-1,1,0.5,null]})) {
    for (const [index,value] of values.entries()) cases.push([field+'/'+index,JSON.stringify({...base,[field]:value})])
  }
  for (const field of ['createdAt','delegationDepth','version']) {
    cases.push([field+'/negative-zero',JSON.stringify(base).replace('"'+field+'":'+String((base as any)[field]),'"'+field+'":-0')])
    const missing: any = {...base}
    delete missing[field]
    cases.push([field+'/missing',JSON.stringify(missing)])
  }
  cases.push(['version/infinite',JSON.stringify(base).replace('"version":0','"version":1e999')])
  cases.push(['retired-sandbox',JSON.stringify({...base,sandboxMode:null})])
  cases.push(['retired-approval',JSON.stringify({...base,approvalPolicy:null})])

  for (const [index,[id,line]] of cases.entries()) {
    inputs.push({id,line})
    rows.push({id:'metadata-format/'+id,metadata:formatObserved(() => parseHeaderMeta(line)),
      scan:formatObserved(() => scanLog(Buffer.from(line+'\n')))})
    for (const compression of ['zstd','none'] as const) {
      const root = join(directory,'source-metadata',compression,String(index))
      if (existsSync(root)) throw new Error('Metadata observation requires a fresh workspace')
      const path = join(root,'_no-cwd','raw','session.jsonl'+(compression === 'zstd' ? '.zstd' : ''))
      await mkdir(dirname(path),{recursive:true})
      const plain = Buffer.from(line+'\n')
      const encoded = compression === 'zstd' ? await compressZstdFrame(plain) : plain
      await writeFile(path,encoded)
      const ctx = new Context()
      await ctx.plugin(Sessions)
      const fiber = await ctx.plugin(Jsonl,{root,compression})
      const provider:any = ctx.sessionPersistence
      const invoke:any = {stored:() => provider.loadStored('raw'),raw:() => provider.readRaw('raw'),
        list:() => provider.list(),suffix:() => provider.readFrom('raw',0),inspect:() => provider.inspect('raw')}
      try {
        for (const operation of operations) {
          rows.push({id:'metadata-public/'+compression+'/'+id+'/'+operation,
            observation:await observed(invoke[operation],root),artifactSha256:sha(encoded),
            unchanged:readFileSync(path).equals(encoded)})
        }
      } finally {await fiber.dispose();await ctx.fiber.dispose()}
      if (!readFileSync(path).equals(encoded)) throw new Error('Metadata observation changed the artifact')
    }
  }
  writeFileSync(join(directory,'source-metadata.json'),JSON.stringify({node:process.versions.node,inputs,rows},null,2)+'\n')
},30000)
