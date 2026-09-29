import { it, expect } from 'vitest'
import { readFileSync, writeFileSync } from 'node:fs'
import { toPiReplayState, toPiAssistant } from '../../reference/packages/llm/llm-pi-ai/src/replay.ts'
import { toStreamChunks } from '../../reference/packages/llm/llm-pi-ai/src/stream.ts'

it('observes pinned pi-ai stream and replay boundaries', async () => {
  const fixtures = JSON.parse(readFileSync('scripts/oracles/pi-fixtures.json', 'utf8'))
  const rows: any[] = []
  for (const fixture of fixtures) {
    const row: any = {id: fixture.id}
    try {
      if (fixture.kind === 'replay') row.value = toPiReplayState(fixture.message)
      if (fixture.kind === 'assistant') {
        let degraded = 0
        row.value = {message: toPiAssistant(fixture.message, () => degraded++), degraded}
      }
      if (fixture.kind === 'stream') {
        row.value = []
        const signal = new AbortController()
        if (fixture.aborted) signal.abort()
        async function* events() { for (const event of fixture.events) yield event }
        for await (const chunk of toStreamChunks(events(), fixture.contextWindow, signal.signal)) row.value.push(chunk)
      }
    } catch (error: any) { row.error = {code: error.code ?? error.name} }
    rows.push(row)
  }
  expect(rows.length).toBe(fixtures.length)
  writeFileSync(process.env.PI_OUTPUT!, JSON.stringify(rows, null, 2))
})
