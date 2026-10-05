import {it} from 'vitest'
import {Context} from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import JsonlPersistence from '@deepseek-ai/dsh-session-persistence-jsonl'
import {oneTurnLog} from '../../reference/packages/session/session-persistence/tests/contract.ts'
import {createHash} from 'node:crypto'
import {existsSync, readFileSync, writeFileSync} from 'node:fs'
import {join, relative} from 'node:path'

const directory = process.env.JSONL_PROVIDER_DIRECTORY!
const phase = process.env.JSONL_PROVIDER_PHASE!
const sha = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex')

it('observes actual original compressed and plaintext providers and mutual files', async () => {
  const rows: any[] = []
  const inputs: any[] = []
  for (const compression of ['zstd','none'] as const) {
    for (const packChunks of [true,false]) {
      const key = compression + '-' + String(packChunks)
      const root = join(directory, (phase === 'produce' ? 'source-' : 'native-') + key)
      const context = new Context()
      await context.plugin(SessionStore)
      const fiber = await context.plugin(JsonlPersistence, {root, compression, packChunks})
      const provider: any = context.sessionPersistence
      const metadata: any = {id:'mutual-'+key+'中文😀', version:0, createdAt:1234, cwd:'C:/jsonl-provider-fixture', delegationDepth:0}
      const events = oneTurnLog()
      if (phase === 'produce') {
        const lazy = !existsSync(root)
        await provider.create(metadata)
        const detached = !existsSync(root)
        await provider.append(metadata.id, events.slice(0,3))
        const path = provider.locate(metadata).path
        const prior = readFileSync(path)
        await provider.append(metadata.id, events.slice(3))
        const appended = readFileSync(path)
        inputs.push({key, compression, packChunks, metadata, events, path, revision:await provider.readStoredRevision(metadata.id)})
        rows.push({id:'materialization/'+key,lazy,detached,retained:appended.subarray(0,prior.length).equals(prior),
          sha256:sha(appended),relative:relative(root,path).replaceAll('\\','/')})
      } else {
        const revisions = JSON.parse(readFileSync(join(directory,'native-revisions.json'),'utf8'))
        if (await provider.readStoredRevision(metadata.id) !== revisions[key]) throw new Error('Native cross-file full revision differs')
        const loaded = await provider.load(metadata.id)
        const inspected = await provider.inspect(metadata.id)
        const suffix = await provider.readFrom(metadata.id, 2)
        const raw = await provider.readRaw(metadata.id)
        const prepared = await provider.prepare(metadata.id)
        rows.push({id:'mutual/'+key,meta:loaded.meta,events:loaded.events,inspected:inspected.events.length,suffix:suffix.events,
          raw:raw.content,filename:raw.filename,prepared:prepared.session.events.length,
          endSeed:prepared.session.events.at(-1)!.type,unpublished:context.sessions.get(metadata.id) === undefined, revisionMatched:true})
        prepared[Symbol.dispose]()
      }
      await fiber.dispose()
    }
  }
  writeFileSync(join(directory,'source-'+phase+'.json'), JSON.stringify({node:process.versions.node,rows,inputs},null,2)+'\n')
})
