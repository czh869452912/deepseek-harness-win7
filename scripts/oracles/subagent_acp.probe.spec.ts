import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it } from 'vitest'
import { startAcpRun } from '../../reference/packages/subagent/subagent-acp/src/run.ts'
import * as backend from '../../reference/packages/subagent/subagent-acp/src/index.ts'
import { spawnSubprocess } from '../../reference/packages/subprocess/subprocess-local/src/spawn.ts'

async function waitForFile(path: string) {
  const deadline = Date.now() + 10000
  while (!existsSync(path)) {
    if (Date.now() > deadline) throw new Error('ACP peer readiness not observed')
    await new Promise(resolve => setTimeout(resolve, 10))
  }
}

it('observes actual original ACP subprocess runs and safe failure facts', async () => {
  const workspace = process.env.SUBAGENT_ACP_WORKSPACE!
  const scenarios: any[] = ['end_turn', 'max_tokens', 'refusal', 'cancelled', 'max_turn_requests']
    .map(reason => ({name: 'stop-' + reason, env: {PROBE_STOP: reason, PROBE_THOUGHT: '1'}}))
  for (const policy of ['reject', 'allow']) {
    for (const reason of ['end_turn', 'refusal', 'max_turn_requests']) {
      scenarios.push({name: 'permission-' + policy + '-' + reason, policy,
        env: {PROBE_PERMISSION: '1', PROBE_IGNORE_PERMISSION: '1', PROBE_STOP: reason, PROBE_TOOL_KIND: 'execute'}})
    }
  }
  scenarios.push({name: 'no-allow', policy: 'allow', env: {PROBE_PERMISSION: '1', PROBE_NO_ALLOW: '1'}},
    {name: 'unknown-kind', env: {PROBE_PERMISSION: '1', PROBE_IGNORE_PERMISSION: '1', PROBE_STOP: 'refusal', PROBE_TOOL_KIND: 'future-kind'}},
    {name: 'cwd', env: {PROBE_ECHO_CWD: '1'}},
    {name: 'ambient', env: {PROBE_ECHO_ENV: 'AMBIENT_SECRET'}},
    {name: 'explicit', env: {PROBE_ECHO_ENV: 'EXPLICIT_TOKEN', EXPLICIT_TOKEN: 'child-owned'}},
    {name: 'flush', env: {PROBE_FLUSH: join(workspace, 'source-flush')}},
    {name: 'cancel-noncooperative', cancel: true, env: {PROBE_HANG: '1', PROBE_IGNORE_CANCEL: '1', PROBE_IGNORE_EOF: '1', PROBE_READY: join(workspace, 'source-ready')}},
    {name: 'crash-initialize', env: {PROBE_CRASH_INITIALIZE: '1'}},
    {name: 'crash-after-chunk', env: {PROBE_CRASH_AFTER_CHUNK: '1'}},
    {name: 'missing-session', env: {PROBE_MISSING_ID: '1'}},
    {name: 'spawn-failure', command: join(workspace, 'private-token-no-executable'), env: {}})
  const rows: any[] = []
  for (const scenario of scenarios) {
    const record = join(workspace, 'source-' + scenario.name + '.jsonl')
    const controller = new AbortController()
    const errors: Error[] = []
    let child: any
    const spec = {command: scenario.command ?? process.env.SUBAGENT_ACP_PYTHON!,
      args: [process.env.SUBAGENT_ACP_PEER!], cwd: workspace, permission: scenario.policy ?? 'reject',
      env: {...scenario.env, PROBE_RECORD: record}, disposeEofGraceMs: 150, disposeGraceMs: 100,
      spawn: (spawnSpec: any) => (child = spawnSubprocess(spawnSpec)), onError: (error: Error) => {errors.push(error)}}
    const observations: any = {}
    let run: any
    try {
      run = await startAcpRun({parent: {session: {header: {cwd: workspace}}}, signal: controller.signal,
        prompt: [{type: 'image', source: {type: 'url', url: 'private-parent'}}, {type: 'text', text: 'explicit child task'}]} as any, spec as any)
      if (scenario.cancel) {
        await waitForFile(scenario.env.PROBE_READY)
        controller.abort('local cancel')
      }
      observations.result = await run.result
      if (scenario.cancel) {
        const deadline = Date.now() + 10000
        while (!existsSync(record) || !readFileSync(record, 'utf8').includes('"method": "session/cancel"')) {
          if (Date.now() > deadline) throw new Error('ACP cancel delivery not observed')
          await new Promise(resolve => setTimeout(resolve, 10))
        }
      }
      observations.idDistinct = run.id !== 'same-child-id'
      observations.localAgentAbsent = run.localAgent === undefined
      await run.dispose()
      await run.dispose()
    } catch (error: any) {
      observations.error = {name: error.name, message: error.message}
    } finally {
      if (run) await run.dispose()
    }
    observations.quiescent = await child.waitForExit()
    observations.exitCode = child.pid <= 0 ? null : (await child.done).exitCode
    observations.errorCount = errors.length
    observations.records = existsSync(record) ? readFileSync(record, 'utf8').trim().split('\n').map(line => JSON.parse(line)) : []
    observations.spawned = child.pid > 0
    observations.flushed = scenario.name === 'flush' ? existsSync(scenario.env.PROBE_FLUSH) : false
    rows.push({name: scenario.name, scenario, observations})
    expect(observations.quiescent).toBe(true)
  }
  const configurations: any[] = []
  for (const input of [{command: 'fixture'}, {command: 'fixture', disposeGraceMs: 0},
    {command: 'fixture', disposeEofGraceMs: 2147483648}, {command: 'fixture', cwd: ''},
    {command: 'fixture', cwd: workspace}, {command: 'fixture', disposeGraceMs: 0.5}]) {
    const observation: any = {input}
    try {
      const config = backend.Config(input)
      let provider: any
      backend.apply({subagents: {registerProvider: (value: any) => {provider = value}}} as any, config)
      observation.result = {config, name: provider.name, capabilities: provider.capabilities, inheritsParentContext: provider.inheritsParentContext}
    } catch (error: any) {observation.error = {name: error.name, message: error.message}}
    configurations.push(observation)
  }
  writeFileSync(process.env.SUBAGENT_ACP_OUTPUT!, JSON.stringify({rows, configurations}, null, 2) + '\n')
}, 60000)
