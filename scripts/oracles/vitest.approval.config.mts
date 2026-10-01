import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'

// Execute the pinned upstream source assertions without rewriting their bodies.
export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/interaction/user-approval/tests/approval.spec.ts',
  'reference/packages/interaction/user-approval/tests/invariant.spec.ts',
  'scripts/oracles/approval.spec.ts',
] } })
