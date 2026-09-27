import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/core/session/tests/repair.spec.ts',
  'reference/packages/session/session-persistence/tests/preparations.spec.ts',
  'reference/packages/session/session-persistence/tests/write-behind.spec.ts',
  'reference/packages/session/session-persistence-jsonl/tests/jsonl.spec.ts',
] } })
