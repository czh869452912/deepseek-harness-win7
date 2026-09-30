import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'

export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/guard/repeat-tool-reminder/tests/repeat-tool-reminder.spec.ts',
] } })
