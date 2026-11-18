import { readFile, writeFile, mkdtemp, rm, copyFile, cp, stat, utimes, access } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore from '@deepseek-ai/dsh-session'
import * as Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl'

it('observes actual durable snapshot qualification, stable reopening, copied stores and caller abort', async () => {
  const rows: any[] = []
  for (const backend of ['jsonl','jsonl-zstd']) {
    const modes = ['lazy','stable','append','noop','detached','reopen','copy','preabort',
      ...(backend === 'jsonl' ? ['restored-stat'] : [])]
    for (const mode of modes) {
      const parent = await mkdtemp(join(tmpdir(),'dsh-snapshot-'))
      const root = join(parent,'original')
      const file = join(parent,'original.db')
      const meta = {version:4,id:'s',createdAt:1,cwd:'/controlled/cwd',isSeeded:false} as any
      const firstEvent = {type:'session/end-seed',seq:0,time:1,data:{}} as any
      let context: Context | undefined
      const mount = async (location: string) => {
        context = new Context()
        await context.plugin(SessionStore)
        await context.plugin(Jsonl, {root:location,compression:backend === 'jsonl' ? 'none' : 'zstd'})
        return context.sessionPersistence
      }
      const grammar = (token: string) => backend.startsWith('jsonl') ? /^\d+:\d+:\d+:-?\d+:-?\d+$/.test(token)
        : /^(?:file:\d+:\d+:-?\d+|memory):store:[0-9a-f-]{36}:incarnation:[0-9a-f-]{36}:revision:\d+$/.test(token)
      const observed: any = {}
      const reason = new TypeError('snapshot deadline')
      try {
        let persistence = await mount(mode === 'memory' ? ':memory:' : backend.startsWith('jsonl') ? root : file)
        const writer = await persistence.create(meta)
        if (mode === 'lazy') {
          observed.count = (await persistence.list()).length
          observed.physicalExists = await access(persistence.locate(meta)!.path).then(() => true, () => false)
        }
        else if (mode === 'preabort') {
          const controller = new AbortController()
          controller.abort(reason)
          await persistence.list({signal:controller.signal})
        } else {
          await writer.append([firstEvent])
          await writer.flush()
          const initial = (await persistence.list())[0]
          if (mode === 'stable') {
            const repeated = await persistence.list()
            const identity = await stat(backend.startsWith('jsonl') ? persistence.locate(meta)!.path : file,{bigint:true})
            const prefix = backend.startsWith('jsonl')
              ? [identity.dev,identity.ino,identity.size,identity.mtimeNs].join(':')+':'
              : 'file:'+ [identity.dev,identity.ino,identity.birthtimeNs].join(':')+':store:'
            Object.assign(observed,{count:repeated.length,same:repeated[0].revision===initial.revision,
              qualified:grammar(initial.revision),statIdentity:initial.revision.startsWith(prefix)})
          } else if (mode === 'append' || mode === 'memory') {
            await writer.append([
              {type:'turn/start',seq:1,time:2,data:{turn:1}},
              {type:'turn/end',seq:2,time:3,data:{turn:1,reason:{kind:'completed'}}},
            ] as any)
            await writer.flush()
            const next = (await persistence.list())[0]
            if (mode === 'memory') Object.assign(observed,{qualified:grammar(initial.revision),
              same:(await persistence.list())[0].revision===next.revision,
              counterDelta:Number(next.revision.split(':').at(-1))-Number(initial.revision.split(':').at(-1))})
            else {
              observed.changed = initial.revision !== next.revision
              if (backend === 'sqlite') observed.counterDelta = Number(next.revision.split(':').at(-1))-Number(initial.revision.split(':').at(-1))
            }
          } else if (mode === 'noop') {
            await writer.append([])
            observed.same = (await persistence.list())[0].revision === initial.revision
          } else if (mode === 'detached') {
            initial.header.createdAt = 999
            const repeated = (await persistence.list())[0]
            Object.assign(observed,{createdAt:repeated.header.createdAt,sameToken:repeated.revision===initial.revision})
          } else if (mode === 'reopen' || mode === 'copy') {
            await writer.close()
            await context!.fiber.dispose()
            context = undefined
            let location = backend.startsWith('jsonl') ? root : file
            if (mode === 'copy') {
              location = backend.startsWith('jsonl') ? join(parent,'copied') : join(parent,'copied.db')
              if (backend.startsWith('jsonl')) await cp(root,location,{recursive:true})
              else await copyFile(file,location)
            }
            persistence = await mount(location)
            const repeated = (await persistence.list())[0]
            if (mode === 'reopen') Object.assign(observed,{same:repeated.revision===initial.revision,qualified:grammar(repeated.revision)})
            else Object.assign(observed,{sameHeader:JSON.stringify(repeated.header)===JSON.stringify(initial.header),
              different:repeated.revision!==initial.revision,qualified:grammar(repeated.revision)})
          } else {
            const path = persistence.locate(meta)!.path
            await utimes(path,1_000_000_000,1_000_000_000)
            const fixture = (value: string) => {
              const result = spawnSync(process.env.SESSION_SNAPSHOTS_PYTHON!,
                ['-I', 'scripts/oracles/session_snapshot_fixture.py', path, value], {encoding:'utf8'})
              if (result.status !== 0 || result.stderr) throw new Error('snapshot metadata fixture failed: ' + result.stderr)
            }
            fixture('1500000000000000000')
            const before = await stat(path,{bigint:true})
            const first = (await persistence.list())[0]
            const bytes = await readFile(path)
            bytes[bytes.length-2] = 32
            await writeFile(path,bytes)
            await utimes(path,1_000_000_000,1_000_000_000)
            fixture('1500000001000000000')
            const after = await stat(path,{bigint:true})
            await writer.flush()
            const next = (await persistence.list())[0]
            Object.assign(observed,{sameSize:before.size===after.size,sameFile:before.ino===after.ino,
              sameMtime:before.mtimeNs===after.mtimeNs,changedToken:first.revision!==next.revision,
              changeFieldAdvanced:BigInt(next.revision.split(':').at(-1)!)>BigInt(first.revision.split(':').at(-1)!)})
          }
        }
        await writer.close()
      } catch (error: any) {
        observed.error = {name:error.name,message:error.message,sameReason:error===reason}
      } finally {
        if (context) await context.fiber.dispose()
        await rm(parent,{recursive:true,force:true})
      }
      rows.push({name:backend+'-'+mode,observed})
    }
  }
  await writeFile(process.env.SESSION_SNAPSHOTS_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
})
