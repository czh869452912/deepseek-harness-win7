import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.consumers.config.mts'
export default defineConfig({ ...base, test: { ...base.test, include: [
  'reference/packages/client/connection/tests/api-request-trust.host.spec.ts',
  'reference/packages/client/connection/tests/rpc-schema.host.spec.ts',
  'reference/packages/api/gateway/tests/stream-protocol.host.spec.ts',
  'reference/packages/api/gateway/tests/remote-event-protocol.host.spec.ts',
] } })
