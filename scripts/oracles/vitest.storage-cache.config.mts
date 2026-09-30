import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/storage/storage-domain/tests/domain.spec.ts',
  'reference/packages/storage/storage-domain/tests/invariant.spec.ts',
  'reference/packages/session/session-projection-cache/tests/cache.spec.ts',
] } })
