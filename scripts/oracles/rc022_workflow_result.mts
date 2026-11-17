import { load } from './rc022_subagent_fixture.mts'
import { getEventListeners } from 'node:events'
const { PtcWorkflowRun } = await load('packages/workflow/workflow-ptc/src/host.ts')
async function scenario(kind: string) {
  const entered = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
  const closing = Promise.withResolvers<void>(), closed = Promise.withResolvers<void>()
  const external = new AbortController(), callbacks: boolean[] = [], disposed: string[] = []
  const ctx = { workingDirectory: { async ensure() { return 'C:/fixed' } }, logger: { warn() {} } }
  const subagents = { async startActivation() {
    return { childId: 'child', result: Promise.resolve({ output: [], stopReason: 'completed' }), async dispose() {
      closing.resolve(); await closed.promise; disposed.push('child')
    } }
  } }
  const runtime = { sandboxMode: 'read-only', programFormat: 'function-body', resolve: (x: any) => x, async run(spec: any) {
    if (kind === 'teardown') await spec.bindings[0].functions.startChild({ prompt: 'child' })
    entered.resolve(); await release.promise
    if (kind === 'runtime-error') throw Error('runtime rejected')
    return { value: { value: 7, stopReason: 'completed', agentsStarted: kind === 'teardown' ? 1 : 0 } }
  } }
  const run = new PtcWorkflowRun(ctx, subagents, runtime, 'run', { name: 'held' }, null, {}, 'stub', { mode: 'read-only' }, null, external.signal)
  const result = run.result
  let settled = false, secondSettled = false
  result.then(() => { settled = true; callbacks.push(run.result === result) })
  if (kind !== 'early-observer') await entered.promise
  if (kind === 'teardown') { release.resolve(); await closing.promise }
  const abandoned = Promise.withResolvers<void>()
  const first = Promise.race([result, abandoned.promise])
  const second = result.then((value: any) => { secondSettled = true; return value })
  abandoned.resolve(); await first
  const pending = !settled && !secondSettled, stillActive = !run.controller.signal.aborted, heldChildren = run.children.size
  if (kind === 'owner-cancel') run.cancel('holder stopped')
  release.resolve(); closed.resolve()
  const answer = await second
  await run.dispose()
  if (answer.error) answer.error = answer.error.split('\n')[0].replace(/^Error: /, '')
  return { kind, pending, stillActive, heldChildren, sameHandle: run.result === result, sameValue: await result === answer,
    result: answer, callbacks, disposed, pendingJobs: run.pending.size, children: run.children.size,
    detached: getEventListeners(external.signal, 'abort').length === 0 }
}
const rows = []
for (const kind of ['abandoned-observer', 'timeout', 'early-observer', 'teardown', 'runtime-error', 'owner-cancel']) rows.push(await scenario(kind))
process.stdout.write(JSON.stringify(rows))
