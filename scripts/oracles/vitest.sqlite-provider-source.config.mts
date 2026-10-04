import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
import {fileURLToPath} from 'node:url'

export default defineConfig({...base, resolve: {alias: [...base.resolve!.alias as any[],
  {find: /^typescript$/, replacement: fileURLToPath(new URL('./official/node_modules/typescript/lib/typescript.js', import.meta.url))},
  {find: /^fast-check$/, replacement: fileURLToPath(new URL('./official/node_modules/fast-check/lib/fast-check.js', import.meta.url))},
]}, test: {...base.test, include: [
  'reference/packages/session/session-persistence-sqlite/tests/differential.spec.ts',
  'reference/packages/session/session-persistence-sqlite/tests/sql-resource-boundary.spec.ts',
]}})
