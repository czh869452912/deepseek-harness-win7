import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
export default defineConfig({...base, test: {...base.test, include: [
  'reference/packages/session-query/session-query/tests/session-query.spec.ts',
  'reference/packages/session-query/session-query/tests/tracing.spec.ts',
  'reference/packages/session-query/session-query/tests/search-helpers.spec.ts']}})
