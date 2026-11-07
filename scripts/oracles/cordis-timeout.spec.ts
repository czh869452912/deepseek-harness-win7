import { expect, it } from 'vitest'
import { writeFile } from 'node:fs/promises'
import { performance } from 'node:perf_hooks'
import { createSandbox, evaluateHostCode } from '../../reference/packages/extensions/cordis-host-runner/src/sandbox.ts'

it('bounds the pinned evaluator synchronous native call but permits its async continuation', async () => {
  let late = false
  const started = performance.now()
  const sandbox = createSandbox('timeout-probe', {
    block: () => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 600),
    late: () => { late = true },
  })
  let timeoutMessage = ''
  try {
    await evaluateHostCode(sandbox, 'harness.block(); harness.late(); return () => {}', 'timeout-probe', 30)
  } catch (error) {
    timeoutMessage = String(error)
  }
  const elapsedMs = performance.now() - started
  expect(timeoutMessage).toContain('timed out')
  expect(elapsedMs).toBeLessThan(400)
  expect(late).toBe(false)
  const asyncSandbox = createSandbox('async-probe', {
    wait: () => new Promise(resolve => setTimeout(resolve, 80)),
  })
  const plugin = await evaluateHostCode(asyncSandbox, 'await harness.wait(); return () => {}', 'async-probe', 30)
  expect(typeof plugin).toBe('function')
  await new Promise(resolve => setTimeout(resolve, 650))
  expect(late).toBe(false)
  await writeFile(process.env.CORDIS_TIMEOUT_OBSERVATION!, JSON.stringify({
    elapsedMs, timeoutMessage, late, asyncPluginType: typeof plugin,
  }, null, 2) + '\n')
})
