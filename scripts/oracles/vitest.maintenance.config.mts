import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/core/agent-loop/tests/loop.spec.ts',
  'reference/packages/core/agent-loop/tests/cancel.spec.ts',
  'reference/packages/core/agent-loop/tests/scope-lifecycle.spec.ts',
  'reference/packages/compaction/compaction-basic/tests/manual-compaction.spec.ts',
] } })
