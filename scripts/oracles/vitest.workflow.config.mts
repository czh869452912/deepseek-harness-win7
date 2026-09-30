import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
import { fileURLToPath } from 'node:url'

process.env.TSX_TSCONFIG_PATH = fileURLToPath(new URL('../../reference/tsconfig.base.json', import.meta.url))

export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/core/tools/tests/tools.spec.ts',
  'reference/packages/workflow/tool-ralph/tests/tool-ralph.spec.ts',
  'reference/packages/workflow/tool-workflow/tests/tool-workflow.spec.ts',
  'reference/packages/workflow/tool-workflow/tests/invariant.spec.ts',
  'reference/packages/workflow/workflow-worker-thread/tests/meta.spec.ts',
  'reference/packages/workflow/workflow-worker-thread/tests/realm.spec.ts',
] } })
