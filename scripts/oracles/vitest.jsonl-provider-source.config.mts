import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'

export default defineConfig({...base, test: {...base.test, include: [
  'reference/packages/session/session-persistence-jsonl/tests/zstd.spec.ts',
  'reference/packages/session/session-persistence-jsonl/tests/zstd.compat.spec.ts',
]}})
