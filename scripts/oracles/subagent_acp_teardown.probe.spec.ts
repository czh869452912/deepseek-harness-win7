import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { getEventListeners } from 'node:events'
import { expect, it } from 'vitest'
import { startAcpRun } from '../../reference/packages/subagent/subagent-acp/src/run.ts'
import { spawnSubprocess } from '../../reference/packages/subprocess/subprocess-local/src/spawn.ts'

async function waitForFile(path: string) {
  const deadline = Date.now() + 10000
  while (!existsSync(path)) {
    if (Date.now() > deadline) throw new Error('ACP teardown peer readiness not observed')
    await new Promise(resolve => setTimeout(resolve, 10))
  }
}

function failure(error: any): any {
  return {name: error.name, message: error.message,
    ...(error.cause === undefined ? {} : {cause: error.cause.message}),
    ...(error.errors === undefined ? {} : {errors: error.errors.map(failure)})}
}

it('observes actual startup and published subprocess teardown failure ownership', async () => {
  const workspace = process.env.SUBAGENT_ACP_TEARDOWN_WORKSPACE!
  const rows: any[] = []
  const raw = 'rollback leaked /private/path SECRET_TOKEN'
  for (const name of ['published-post-exit', 'startup-post-exit', 'cancelled-startup-post-exit', 'throwing-error-sink']) {
    const record = join(workspace, 'source-' + name + '.jsonl')
    const controller = new AbortController()
    const errors: string[] = []
    let real: any
    let waits = 0
    let terminations = 0
    const env: any = {PROBE_RECORD: record}
    if (name !== 'throwing-error-sink') env.PROBE_IGNORE_EOF = '1'
    if (name === 'startup-post-exit') env.PROBE_MISSING_ID = '1'
    if (name === 'cancelled-startup-post-exit') {
      env.PROBE_NEW_READY = join(workspace, 'source-new-ready')
      env.PROBE_NEW_GO = join(workspace, 'source-new-go')
    }
    if (name === 'throwing-error-sink') env.PROBE_CRASH_AFTER_CHUNK = '1'
    const spec = {command: process.env.SUBAGENT_ACP_PYTHON!, args: [process.env.SUBAGENT_ACP_PEER!],
      cwd: workspace, permission: 'reject', env, disposeEofGraceMs: 30, disposeGraceMs: 30,
      onError: (error: Error) => {
        errors.push(error.message)
        if (name === 'throwing-error-sink') throw new Error('diagnostic sink rejected')
      },
      spawn: (input: any) => {
        real = spawnSubprocess(input)
        if (name === 'throwing-error-sink') return real
        return {pid: real.pid, stdin: real.stdin, stdout: real.stdout, stderr: real.stderr,
          collected: real.collected, done: real.done,
          terminate: () => {terminations++; real.terminate()},
          waitForExit: (signal?: AbortSignal) => {
            waits++
            return signal === undefined ? real.done.then(() => {throw new Error(raw)}) : Promise.resolve(false)
          }}
      }}
    const observed: any = {}
    let run: any
    try {
      const starting = startAcpRun({parent: {session: {header: {cwd: workspace}}}, signal: controller.signal,
        prompt: [{type: 'text', text: 'explicit child task'}]} as any, spec as any)
      if (name === 'cancelled-startup-post-exit') {
        await waitForFile(env.PROBE_NEW_READY)
        controller.abort('startup cancellation')
        writeFileSync(env.PROBE_NEW_GO, 'go')
      }
      run = await starting
      observed.result = await run.result
      const first = await run.dispose().catch((error: unknown) => error)
      const second = await run.dispose().catch((error: unknown) => error)
      observed.disposeFailure = first === undefined ? null : failure(first)
      observed.sameDisposeFailure = first === second
    } catch (error: any) {
      observed.startFailure = failure(error)
    } finally {
      if (run) await run.dispose().catch(() => {})
      expect(await real.waitForExit()).toBe(true)
      observed.actualExit = (await real.done).exitCode
      observed.waits = waits
      observed.terminations = terminations
      observed.rawErrors = errors
      observed.listenerRemoved = getEventListeners(controller.signal, 'abort').length === 0
      observed.records = readFileSync(record, 'utf8').trim().split('\n').map(line => JSON.parse(line))
      rows.push({name, observed})
    }
  }
  writeFileSync(process.env.SUBAGENT_ACP_TEARDOWN_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
}, 60000)
