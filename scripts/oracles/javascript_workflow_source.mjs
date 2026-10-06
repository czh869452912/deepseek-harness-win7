import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { Worker } from 'node:worker_threads'
import { build } from './node_modules/esbuild/lib/main.js'

const sourceCommit = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
if (process.version !== 'v22.22.2') throw new Error('Source observations require pinned Node22.22.2')
if (execFileSync('git', ['-C', 'reference', 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() !== sourceCommit
    || execFileSync('git', ['-C', 'reference', 'status', '--porcelain'], { encoding: 'utf8' }).trim()) {
  throw new Error('Source observations require unchanged pinned Source')
}
const output = resolve(process.argv[2])
if (existsSync(output)) throw new Error('Source observation output must be new')
mkdirSync(output)
const bundle = await build({
  entryPoints: ['reference/packages/workflow/workflow-worker-thread/src/worker.ts'],
  bundle: true, platform: 'node', format: 'cjs', write: false, metafile: true, tsconfig: 'reference/tsconfig.base.json',
  alias: {
    '@deepseek-ai/dsh-llm': resolve('scripts/native/workflow/llm.ts'),
    '@deepseek-ai/dsh-session': resolve('scripts/native/workflow/session.ts'),
    '@deepseek-ai/dsh-tools': resolve('reference/packages/core/tools/src/json-schema.ts'),
  },
})
const workerPath = resolve(output, 'worker.cjs')
writeFileSync(workerPath, bundle.outputFiles[0].contents)
const cases = JSON.parse(readFileSync('tests/fixtures/javascript-workflow/cases.json', 'utf8'))
const observations = []
const rawObservations = []
for (const scenario of cases) {
  const frames = []
  const init = {
    body: scenario.body, meta: { name: scenario.name, description: 'actual Source worker RPC' }, args: { nested: { value: 2 } },
    limits: { maxConcurrentAgents: scenario.concurrent ?? 2, maxTotalAgents: scenario.total ?? 10,
      maxItemsPerCall: scenario.items ?? 30, syncTimeoutMs: 200 },
  }
  const worker = new Worker(workerPath, { workerData: init, execArgv: [], env: { TMP: tmpdir(), TEMP: tmpdir() } })
  let terminal = false
  let semanticSeen = !scenario.waitDisposals
  const disposals = new Set()
  let snapshot
  const completed = new Promise((accept, reject) => {
    const deadline = setTimeout(() => reject(new Error('Source observation deadline: ' + scenario.name)), 5000)
    worker.on('error', error => { clearTimeout(deadline); reject(error) })
    worker.on('exit', code => { if (!terminal) { clearTimeout(deadline); reject(new Error('Source worker exited: ' + code)) } })
    worker.on('message', message => {
      frames.push(message)
      if (message.type === 'ready') {
        worker.postMessage(scenario.cancelBeforeGo ? { type: 'cancel', reason: 'already aborted' } : { type: 'go' })
      } else if (message.type === 'child-start') {
        if (scenario.cancelAtStart) worker.postMessage({ type: 'cancel', reason: 'active child cancellation' })
        worker.postMessage({ type: 'child-started', callId: message.callId, childId: 'child-' + message.callId })
        const prompt = message.request.prompt
        const result = prompt === 'failed' ? { output: [], stopReason: 'error' } : prompt === 'blocks' ? {
          output: [{ type: 'text', text: 'first' }, { type: 'image', data: 'ignored' }, { type: 'text', text: 'second' }],
          stopReason: 'completed',
        } : { output: [{ type: 'text', text: prompt }], stopReason: 'completed',
          ...message.request.schema && prompt !== 'unhonored' ? { structured: { answer: 42 } } : {},
        }
        worker.postMessage({ type: 'child-settled', callId: message.callId, result })
      } else if (message.type === 'child-dispose') {
        worker.postMessage({ type: 'child-disposed', callId: message.callId })
      } else if (message.type === 'result') {
        terminal = true
      }
      if (message.type === (scenario.name === 'dropped-child-continuation' ? 'log' : 'agent-end')) semanticSeen = true
      if (message.type === 'child-dispose') disposals.add(message.callId)
      if (!snapshot && terminal && semanticSeen && disposals.size >= (scenario.waitDisposals ?? 0)) {
        snapshot = structuredClone(frames)
        clearTimeout(deadline)
        accept()
      }
    })
  })
  try {
    await completed
    observations.push({ name: scenario.name, frames: snapshot, aliveAfterResult: worker.threadId !== -1 })
  } finally {
    await worker.terminate()
    rawObservations.push({ name: scenario.name, frames: structuredClone(frames) })
  }
}
const inputs = Object.fromEntries(Object.keys(bundle.metafile.inputs).sort().map(path => [path,
  createHash('sha256').update(readFileSync(path)).digest('hex')]))
writeFileSync(resolve(output, 'source.json'), encodeSource({ sourceCommit, inputs, observations }) + '\n', 'utf8')
writeFileSync(resolve(output, 'raw-observations-after-terminate.json'), encodeSource(rawObservations) + '\n', 'utf8')
console.log(JSON.stringify({ sourceCommit, observations: observations.length }))

function encodeSource(value) {
  if (typeof value === 'number' && Object.is(value, -0)) return '-0.0'
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(encodeSource).join(',') + ']'
  return '{' + Object.keys(value).map(key => JSON.stringify(key) + ':' + encodeSource(value[key])).join(',') + '}'
}
