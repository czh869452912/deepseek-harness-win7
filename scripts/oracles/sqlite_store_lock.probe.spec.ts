import {spawn, spawnSync} from 'node:child_process'
import {once} from 'node:events'
import {join} from 'node:path'
import {writeFileSync} from 'node:fs'
import {it} from 'vitest'
import {SqliteStore} from '../../reference/packages/session/session-persistence-sqlite/src/store.ts'

it('observes original cross-process busy reservation and stale repair refusal', async () => {
  const path = join(process.env.SQLITE_LOCK_DIRECTORY!, 'source.db')
  const python = process.env.SQLITE_LOCK_PYTHON!
  const script = join(process.cwd(), 'scripts/oracles/sqlite_store_lock_peer.py')
  const store = new SqliteStore({path, journalMode: 'wal', busyTimeoutMs: 100})
  const meta: any = {id: 'locked', version: 0, createdAt: 1}
  let peer: ReturnType<typeof spawn> | undefined
  try {
    await store.appendBatch(meta, [{type: 'turn/start', seq: 0, time: 0, data: {turn: 1}} as any], false)
    peer = spawn(python, ['-I', script, '--root', process.env.SQLITE_LOCK_ROOT!, '--path', path, '--mode', 'hold'], {stdio: 'pipe', windowsHide: true})
    let diagnostics = ''
    peer.stderr!.on('data', data => { diagnostics += data.toString() })
    const [ready] = await once(peer.stdout!, 'data')
    if (!JSON.parse(ready.toString()).held) throw new Error('peer did not reserve')
    const before = await store.readStoredRevision(meta.id)
    const started = performance.now()
    let code: number | undefined
    try { await store.appendBatch(meta, [{type: 'turn/end', seq: 1, time: 1, data: {turn: 1}} as any], true) }
    catch (error: any) { code = error.errcode }
    const finiteBudget = performance.now() - started < 2000
    const unchanged = await store.readStoredRevision(meta.id) === before
    const exited = once(peer, 'exit')
    peer.stdin!.end('\n')
    const [exit] = await exited
    peer = undefined
    if (exit !== 0 || diagnostics) throw new Error('peer cleanup failed: ' + diagnostics)
    const winner = spawnSync(python, ['-I', script, '--root', process.env.SQLITE_LOCK_ROOT!, '--path', path, '--mode', 'append'], {encoding: 'utf8', windowsHide: true, timeout: 10000})
    if (winner.status !== 0 || winner.stderr) throw new Error('peer append failed')
    let stale = false
    try { await store.commitRepair(meta, undefined, [{type: 'turn/end', seq: 1, time: 1, data: {turn: 1}} as any]) }
    catch (error: any) { stale = error.message === 'session locked repair is stale: closer starts at seq 1, stored next seq is 2' }
    const loaded = await store.loadStored(meta.id)
    const output = {crossProcessBusyCode: code, revisionUnchangedWhileBlocked: unchanged, finiteBudget,
      staleRepairRefused: stale, winningTailRetained: loaded!.events.length === 2}
    writeFileSync(join(process.env.SQLITE_LOCK_DIRECTORY!, 'source-observations.json'), JSON.stringify({node: process.version, ...output}))
  } finally {
    if (peer) peer.stdin!.end('\n')
    await store.close()
  }
})
