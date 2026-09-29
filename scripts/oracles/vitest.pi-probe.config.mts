import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.deepseek-probe.config.mts'
import { fileURLToPath } from 'node:url'
export default defineConfig({...base,
  resolve: {alias: [...base.resolve!.alias as any[], {
    find: /^@earendil-works\/pi-ai$/,
    replacement: fileURLToPath(new URL('./official/node_modules/@earendil-works/pi-ai/dist/index.js', import.meta.url)),
  }, {
    find: /^@earendil-works\/pi-ai\/(.*)$/,
    replacement: fileURLToPath(new URL('./official/node_modules/@earendil-works/pi-ai/dist/$1.js', import.meta.url)),
  }]},
  test: {...base.test, include: ['scripts/oracles/pi.spec.ts']},
})
