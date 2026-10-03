import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.subagent-acp.config.mts'

export default defineConfig({...base,
  test: {...base.test, include: [
    'reference/packages/subprocess/subprocess-local/tests/spawn.spec.ts',
    'reference/packages/subprocess/subprocess-local/tests/local.spec.ts',
    'reference/packages/subprocess/subprocess-local/tests/process-inspector.spec.ts',
    'reference/packages/subprocess/subprocess-local/tests/windows-inspector.spec.ts',
    'reference/packages/subprocess/subprocess/tests/service.spec.ts',
  ]}})
