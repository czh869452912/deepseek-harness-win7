import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.consumers.config.mts'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  ...base,
  resolve: { alias: [...base.resolve!.alias as any[], {
    find: /^koffi$/, replacement: fileURLToPath(new URL('./official/node_modules/koffi/index.js', import.meta.url)),
  }] },
  test: { ...base.test, include: [
    'reference/packages/core/agent-loop/tests/resume.spec.ts',
    'reference/packages/core/agent-loop/tests/scope-lifecycle.spec.ts',
    'reference/packages/core/agent-loop/tests/config-session-id.spec.ts',
    'reference/packages/core/agent/tests/agent.spec.ts',
  ] },
})
