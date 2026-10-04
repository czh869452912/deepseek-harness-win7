import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'

export default defineConfig({...base, test: {...base.test,
  include: ['scripts/oracles/projection_cache_failure.probe.spec.ts']}})
