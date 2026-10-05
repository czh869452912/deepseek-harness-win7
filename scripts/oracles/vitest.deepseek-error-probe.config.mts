import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.deepseek-probe.config.mts'

export default defineConfig({...base, cacheDir: '.goose/out/deepseek-error-vite-cache', test: {...base.test,
  include: ['scripts/oracles/deepseek_error.probe.spec.ts'], exclude: [], testTimeout: 30000}})
