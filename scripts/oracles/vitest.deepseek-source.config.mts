import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.deepseek-probe.config.mts'

export default defineConfig({...base, cacheDir: '.goose/out/deepseek-source-vite-cache', test: {...base.test,
  include: ['reference/packages/llm/llm-deepseek/tests/**/*.spec.ts', 'reference/packages/llm/llm-retry/tests/**/*.spec.ts'],
  exclude: [], testTimeout: 30000}})
