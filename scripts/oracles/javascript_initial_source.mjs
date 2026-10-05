import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { build } from './node_modules/esbuild/lib/main.js'

const sourceCommit = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
if (process.version !== 'v22.22.2') throw new Error('Pinned Node required')
if (execFileSync('git', ['-C', 'reference', 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== sourceCommit
    || execFileSync('git', ['-C', 'reference', 'status', '--porcelain'], { encoding: 'utf8' }).trim()) throw new Error('Pinned clean Source required')
const workspace = resolve(process.argv[2])
if (existsSync(workspace)) throw new Error('Fresh Source workspace required')
mkdirSync(workspace)
const inputs = {}
for (const [entry, format, name] of [
  ['reference/packages/workflow/workflow-worker-thread/src/host.ts', 'esm', 'host.mjs'],
  ['reference/packages/workflow/workflow-worker-thread/src/worker.ts', 'cjs', 'original-worker.cjs'],
]) {
  const built = await build({ entryPoints: [entry], bundle: true, platform: 'node', format,
    write: false, metafile: true, tsconfig: 'reference/tsconfig.base.json',
    alias: { '@deepseek-ai/dsh-llm': resolve('scripts/native/workflow/llm.ts'),
      '@deepseek-ai/dsh-session': resolve('scripts/oracles/javascript_workflow_session.ts'),
      '@deepseek-ai/dsh-tools': resolve('reference/packages/core/tools/src/json-schema.ts') } })
  writeFileSync(resolve(workspace, name), built.outputFiles[0].contents, { flag: 'wx' })
  for (const path of Object.keys(built.metafile.inputs)) inputs[path] = createHash('sha256').update(readFileSync(path)).digest('hex')
}
const bootstrap = "const entryControl = new Int32Array(require('node:worker_threads').workerData.__entryGate);\n"
  + "Atomics.store(entryControl, 1, 1);\nAtomics.notify(entryControl, 1);\nAtomics.wait(entryControl, 0, 0);\nrequire('./original-worker.cjs');\n"
writeFileSync(resolve(workspace, 'worker.cjs'), bootstrap, { encoding: 'utf8', flag: 'wx' })
inputs['scripts/oracles/javascript_initial_source.mjs'] = createHash('sha256').update(readFileSync('scripts/oracles/javascript_initial_source.mjs')).digest('hex')
const { WorkerRun } = await import(pathToFileURL(resolve(workspace, 'host.mjs')).href)
const observations = []
for (const cancelled of [false, true]) {
  const name = cancelled ? 'cancel-before-entry-exit' : 'before-entry-exit'
  const events = [], requests = []
  const control = new Int32Array(new SharedArrayBuffer(8))
  const meta = { name, description: 'actual entry blocked before Ready emission' }
  const provider = { async start(...request) { requests.push(request); throw new Error('Unexpected child admission') } }
  const init = { body: 'phase("unreachable");return "unreachable"', meta, __entryGate: control.buffer,
    limits: { maxConcurrentAgents: 2, maxTotalAgents: 10, maxItemsPerCall: 30, syncTimeoutMs: 200 } }
  const run = new WorkerRun({ logger: { warn: message => events.push({ type: 'warning', message }) } },
    provider, 'run', meta, { id: 'parent', options: {} }, init, 'spawn', 5000,
    { phase: title => events.push({ type: 'phase', title }), log: message => events.push({ type: 'log', message }),
      agentStart: info => events.push({ type: 'agent-start', info }), agentEnd: info => events.push({ type: 'agent-end', info }) })
  let readyMessages = 0
  const onMessage = run.onMessage.bind(run)
  run.onMessage = message => { if (message.type === 'ready') readyMessages++; return onMessage(message) }
  events.push({ type: 'start' })
  run.result.then(result => events.push({ type: 'end', outcome: {
    stopReason: result.stopReason, error: result.error, agentsStarted: result.agentsStarted } }))
  try {
    const deadline = Date.now() + 5000
    while (Atomics.load(control, 1) !== 1) {
      if (Date.now() > deadline) throw new Error('Entry barrier deadline')
      await new Promise(accept => setImmediate(accept))
    }
    if (cancelled) run.cancel('')
    const exitCode = await run.worker.terminate()
    const result = await run.result
    const before = { entryBlocked: Atomics.load(control, 0) === 0, readyMessages,
      readyAdmitted: false, signalAborted: run.controller.signal.aborted }
    await run.dispose()
    observations.push({ name, result, events, requests, before, exitCode,
      firstResultRetained: result === await run.result, goneAfterDispose: run.worker.threadId === -1 })
  } finally {
    Atomics.store(control, 0, 1)
    Atomics.notify(control, 0)
    await run.dispose()
  }
}
writeFileSync(resolve(workspace, 'source.json'), JSON.stringify({ sourceCommit, node: process.version, inputs,
  bundle: Object.fromEntries(['host.mjs', 'original-worker.cjs', 'worker.cjs'].map(name => [name,
    createHash('sha256').update(readFileSync(resolve(workspace, name))).digest('hex')])), observations }, null, 2) + '\n',
  { encoding: 'utf8', flag: 'wx' })
