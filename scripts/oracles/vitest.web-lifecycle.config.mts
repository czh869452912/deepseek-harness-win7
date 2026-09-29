import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.consumers.config.mts'
export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/client/hmr/tests/node-half.client.spec.ts',
  'reference/packages/api/remotes/tests/remote-events.host.spec.ts',
] } })
