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
  ['reference/packages/workflow/workflow-worker-thread/src/worker.ts', 'cjs', 'worker.cjs'],
]) {
  const built = await build({ entryPoints: [entry], bundle: true, platform: 'node', format,
    write: false, metafile: true, tsconfig: 'reference/tsconfig.base.json',
    alias: { '@deepseek-ai/dsh-llm': resolve('scripts/native/workflow/llm.ts'),
      '@deepseek-ai/dsh-session': resolve('scripts/oracles/javascript_workflow_session.ts'),
      '@deepseek-ai/dsh-tools': resolve('reference/packages/core/tools/src/json-schema.ts') } })
  writeFileSync(resolve(workspace, name), built.outputFiles[0].contents, { flag: 'wx' })
  for (const path of Object.keys(built.metafile.inputs)) inputs[path] = createHash('sha256').update(readFileSync(path)).digest('hex')
}
inputs['scripts/oracles/javascript_ready_source.mjs'] = createHash('sha256').update(readFileSync('scripts/oracles/javascript_ready_source.mjs')).digest('hex')
const { WorkerRun } = await import(pathToFileURL(resolve(workspace, 'host.mjs')).href)
const observations = []
for (const cancelled of [false, true]) {
  const name = cancelled ? 'cancel-before-held-ready-exit' : 'held-ready-exit'
  const events = [], requests = []
  let receiveReady, heldReady
  const ready = new Promise(accept => { receiveReady = accept })
  const meta = { name, description: 'actual ready delivery held across physical exit' }
  const provider = { async start(...request) { requests.push(request); throw new Error('Unexpected child admission') } }
  const init = { body: 'phase("unreachable");return "unreachable"', meta,
    limits: { maxConcurrentAgents: 2, maxTotalAgents: 10, maxItemsPerCall: 30, syncTimeoutMs: 200 } }
  const run = new WorkerRun({ logger: { warn: message => events.push({ type: 'warning', message }) } },
    provider, 'run', meta, { id: 'parent', options: {} }, init, 'spawn', 5000,
    { phase: title => events.push({ type: 'phase', title }), log: message => events.push({ type: 'log', message }),
      agentStart: info => events.push({ type: 'agent-start', info }), agentEnd: info => events.push({ type: 'agent-end', info }) })
  const onMessage = run.onMessage.bind(run)
  run.onMessage = message => {
    if (message.type === 'ready') { heldReady = message; receiveReady(); return }
    return onMessage(message)
  }
  events.push({ type: 'start' })
  run.result.then(result => events.push({ type: 'end', outcome: {
    stopReason: result.stopReason, error: result.error, agentsStarted: result.agentsStarted } }))
  let deadline
  try {
    await Promise.race([ready, new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('Ready deadline')), 5000) })])
    clearTimeout(deadline)
    if (cancelled) run.cancel('')
    const exitCode = await run.worker.terminate()
    const result = await run.result
    const before = { heldReady: !!heldReady, readyAdmitted: false, signalAborted: run.controller.signal.aborted }
    onMessage(heldReady)
    await run.dispose()
    observations.push({ name, result, events, requests, before, exitCode,
      firstResultRetained: result === await run.result, goneAfterDispose: run.worker.threadId === -1 })
  } finally {
    clearTimeout(deadline)
    await run.dispose()
  }
}
writeFileSync(resolve(workspace, 'source.json'), JSON.stringify({ sourceCommit, node: process.version, inputs,
  bundle: Object.fromEntries(['host.mjs', 'worker.cjs'].map(name => [name,
    createHash('sha256').update(readFileSync(resolve(workspace, name))).digest('hex')])), observations }, null, 2) + '\n',
  { encoding: 'utf8', flag: 'wx' })
