import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/session/session-projection/tests/registry.spec.ts',
  'reference/packages/core/session/tests/derived-cache.spec.ts',
  'reference/packages/core/session/tests/fork.spec.ts',
  'reference/packages/core/session/tests/surface.spec.ts',
] } })
