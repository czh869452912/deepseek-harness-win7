import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.acp.config.mts'
import { fileURLToPath } from 'node:url'

export default defineConfig({...base,
  resolve: {alias: [...base.resolve!.alias as any[], {find: /^node-pty$/,
    replacement: fileURLToPath(new URL('./official/node_modules/node-pty/lib/index.js', import.meta.url))},
    {find: /^@deepseek-ai\/dsh-subprocess-local\/src\/(.*)$/,
      replacement: fileURLToPath(new URL('../../reference/packages/subprocess/subprocess-local/src/', import.meta.url)) + '$1'}]},
  test: {...base.test, include: ['reference/packages/subagent/subagent-acp/tests/subagent-acp.spec.ts']}})
