import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.consumers.config.mts'

export default defineConfig({
  ...base,
  test: { ...base.test, include: ['scripts/oracles/runtime_context.probe.spec.ts'] },
})
