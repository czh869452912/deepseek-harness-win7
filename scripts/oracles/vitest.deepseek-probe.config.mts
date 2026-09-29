import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
import { fileURLToPath } from 'node:url'
export default defineConfig({ ...base,
  resolve: { alias: [...base.resolve!.alias as any[], {
    find: /^yaml$/,
    replacement: fileURLToPath(new URL('./node_modules/yaml/dist/index.js', import.meta.url)),
  }, {
    find: /^eventsource-parser\/stream$/,
    replacement: fileURLToPath(new URL('./official/node_modules/eventsource-parser/dist/stream.js', import.meta.url)),
  }] },
  test: { ...base.test, include: ['scripts/oracles/deepseek.spec.ts'] },
})
