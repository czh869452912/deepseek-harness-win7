import { writeFileSync } from 'node:fs'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import { LocalSubprocessRuntime } from '../../reference/packages/subprocess/subprocess-local/src/index.ts'

it('observes actual source pending ownership and synchronous teardown failure fallback', async () => {
  const rows: any[] = []
  for (const name of ['host-exit-contained', 'pending-host-exit', 'mixed-failure', 'single-failure']) {
    const ctx = new Context()
    const fiber = await ctx.plugin(LocalSubprocessRuntime)
    const service = ctx.subprocess as any
    const trace: any[] = []
    const entered = Promise.withResolvers<void>(), release = Promise.withResolvers<void>()
    const waitFailure = new Error('controlled wait failure')
    const terminalFailure = new Error('controlled terminal failure')
    const ordinary = {done: Promise.resolve({exitCode: 0, signal: null}),
      terminate: () => {trace.push(['terminate', 'ordinary'])},
      terminateForHostExit: () => {trace.push(['force', 'ordinary']); if (name === 'host-exit-contained') throw new Error('controlled force failure')},
      waitForExit: async () => {trace.push(['wait', 'ordinary']); entered.resolve();
        if (name === 'pending-host-exit') await release.promise
        if (name.endsWith('failure')) throw waitFailure
        return true}}
    const terminal = {pid: -1, terminate: async () => {trace.push(['terminate', 'terminal']); throw terminalFailure},
      terminateForHostExit: () => {trace.push(['force', 'terminal'])}}
    service.live.add(ordinary)
    if (name === 'host-exit-contained' || name === 'mixed-failure') service.terminals.add(terminal)
    let retained: any, error: any
    try {
      if (name === 'host-exit-contained') {
        service.terminateForHostExit()
        retained = {ordinary: service.live.size, terminals: service.terminals.size}
      } else {
        const disposing = service.disposeManagedProcesses().catch((failure: any) => {error = failure})
        await entered.promise
        if (name === 'pending-host-exit') {
          service.terminateForHostExit()
          retained = {ordinary: service.live.size, terminals: service.terminals.size}
          release.resolve()
        }
        await disposing
      }
      const observed: any = {trace, after: {ordinary: service.live.size, terminals: service.terminals.size}}
      if (retained !== undefined) observed.retained = retained
      if (error !== undefined) observed.error = {name: error.name, message: error.message,
        sameWaitFailure: error === waitFailure, ...(error.errors === undefined ? {} :
          {members: error.errors.map((member: any) => ({name: member.name, message: member.message})),
            memberIdentity: error.errors[0] === waitFailure && error.errors[1] === terminalFailure})}
      rows.push({name, observed})
    } finally {
      service.live.clear(); service.terminals.clear()
      await fiber.dispose()
    }
  }
  writeFileSync(process.env.SUBPROCESS_OWNERSHIP_OUTPUT!, JSON.stringify(rows, null, 2) + '\n')
}, 15000)
