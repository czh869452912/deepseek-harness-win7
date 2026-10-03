import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.subagent-acp.config.mts'

export default defineConfig({...base,
  test: {...base.test, include: ['scripts/oracles/subprocess_ownership.probe.spec.ts']}})
