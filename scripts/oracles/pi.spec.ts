import { it, expect, vi } from 'vitest'
import { readFileSync, writeFileSync } from 'node:fs'
import { toPiReplayState, toPiAssistant } from '../../reference/packages/llm/llm-pi-ai/src/replay.ts'
import { toStreamChunks } from '../../reference/packages/llm/llm-pi-ai/src/stream.ts'
import { toPiContext } from '../../reference/packages/llm/llm-pi-ai/src/context.ts'
import { resolveProfiles } from '../../reference/packages/llm/llm-pi-ai/src/config.ts'
import { PiAiAdapter } from '../../reference/packages/llm/llm-pi-ai/src/adapter.ts'
import { transformMessages } from './official/node_modules/@earendil-works/pi-ai/dist/api/transform-messages.js'
import { convertMessages } from './official/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js'

it('observes pinned pi-ai stream and replay boundaries', async () => {
  const fixtures = JSON.parse(readFileSync('scripts/oracles/pi-fixtures.json', 'utf8'))
  const rows: any[] = []
  for (const fixture of fixtures) {
    const row: any = {id: fixture.id}
    try {
      if (fixture.kind === 'completions-messages') row.value = convertMessages(fixture.model, fixture.context, fixture.compat)
      if (fixture.kind === 'transform') {
        const clock = vi.spyOn(Date, 'now').mockReturnValue(123)
        try {
          row.value = transformMessages(fixture.messages, fixture.model,
            fixture.normalize ? id => id.replaceAll('|', '_') : undefined)
        } finally { clock.mockRestore() }
      }
      if (fixture.kind === 'catalog') {
        row.value = []
        const profiles = resolveProfiles(fixture.providers)
        const adapter = new PiAiAdapter({profiles: () => profiles} as any)
        for (const [id, profile] of profiles) {
          const models = profile.piProvider.getModels()
          row.value.push({id, displayName: profile.displayName, models,
            configuredMaxTokens: Object.fromEntries(profile.configuredMaxTokens),
            streamIdleTimeoutMs: profile.streamIdleTimeoutMs,
            maxRequestImageBytes: profile.maxRequestImageBytes,
            requestImagePixelBudget: profile.requestImagePixelBudget,
            requestImageMaxBytes: profile.requestImageMaxBytes,
            retryPolicy: profile.retryPolicy,
            info: await Promise.all(models.map(model => adapter.resolveModel(id, model.id))),
          })
        }
      }
      if (fixture.kind === 'context') {
        let degraded = 0
        const reads: any[] = []
        const images = fixture.images === undefined ? undefined : {
          attachments: {readImageRequest: async (ref: any, policy: any) => {
            reads.push({id: ref.attachmentId, policy})
            const version = fixture.images[ref.attachmentId]
            return {...version, data: Buffer.from(version.data, 'base64')}
          }},
          resolveImageAccess: (ref: any) => fixture.access?.[ref.attachmentId] === undefined ? undefined : {readonlyPath: fixture.access[ref.attachmentId]},
          maxRequestImageBytes: fixture.maxBytes,
          requestImagePolicy: fixture.policy,
        }
        row.value = {context: await toPiContext(fixture.options, images as any, () => degraded++), degraded, reads}
      }
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
