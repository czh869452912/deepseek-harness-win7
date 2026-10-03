import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  ...base,
  resolve: { alias: [...base.resolve!.alias as any[], {
    find: /^@agentclientprotocol\/sdk$/,
    replacement: fileURLToPath(new URL('./official/node_modules/@agentclientprotocol/sdk/dist/acp.js', import.meta.url)),
  }, {
    find: /^@modelcontextprotocol\/sdk\/(.*)$/,
    replacement: fileURLToPath(new URL('./official/node_modules/@modelcontextprotocol/sdk/dist/esm/', import.meta.url)) + '$1',
  }] },
  test: { ...base.test, include: ['reference/packages/acp/acp/tests/*.spec.ts'],
    env: { NODE_OPTIONS: '--import=' + new URL('./acp-sdk-resolution.mjs', import.meta.url).href } },
})
