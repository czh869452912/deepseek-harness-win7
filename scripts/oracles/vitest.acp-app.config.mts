import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.acp.config.mts'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  ...base,
  resolve: { alias: [...base.resolve!.alias as any[], {
    find: /^commander$/,
    replacement: fileURLToPath(new URL('./official/node_modules/commander/index.js', import.meta.url)),
  }] },
  test: { ...base.test, include: ['reference/packages/bundle/acp-app/tests/*.spec.ts'] },
})
