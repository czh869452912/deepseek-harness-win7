import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
import { fileURLToPath } from 'node:url'
export default defineConfig({ ...base,
  resolve: { alias: [...base.resolve!.alias as any[], {
    find: /^eventsource-parser\/stream$/,
    replacement: fileURLToPath(new URL('./official/node_modules/eventsource-parser/dist/stream.js', import.meta.url)),
  }] },
  test: { ...base.test, include: ['scripts/oracles/deepseek.spec.ts'] },
})
