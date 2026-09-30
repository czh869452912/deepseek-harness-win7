import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.consumers.config.mts'

export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/util/timeout/tests/timeout.spec.ts',
  'reference/packages/guard/timeout-policy/tests/timeout-policy.spec.ts',
] } })
