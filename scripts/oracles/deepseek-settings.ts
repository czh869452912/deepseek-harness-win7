import { Context } from '@deepseek-ai/cordis'
import LlmRuntime from '@deepseek-ai/dsh-llm'
import { FileSettingsProvider } from '@deepseek-ai/dsh-settings-file'
import * as DeepSeek from '../../reference/packages/llm/llm-deepseek/src/index.ts'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export async function observeSettings(fixture: any) {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-paired-settings-'))
  const ctx = new Context()
  try {
    await ctx.plugin(LlmRuntime)
    const settings = ctx.plugin(FileSettingsProvider, {path: join(directory, 'settings.yaml'), watch: false})
    await settings
    await ctx.plugin(DeepSeek, fixture.config)
    const snapshot = async () => ({models: await ctx.llm.listModels('deepseek-official'),
      retry: ctx.llm.providerRetryPolicy('deepseek-official'), providers: ctx.llm.listProviders()})
    const observations: any[] = [{snapshot: await snapshot()}]
    for (const update of fixture.updates) {
      let accepted = true
      try { await ctx.settings.update('llm-deepseek' as any, update) } catch { accepted = false }
      observations.push({accepted, snapshot: await snapshot()})
    }
    await settings.dispose()
    observations.push({detached: true, snapshot: await snapshot()})
    return observations
  } finally {
    await ctx.fiber.dispose()
    await rm(directory, {recursive: true, force: true})
  }
}
