import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import base from './vitest.deepseek-probe.config.mts'

export default defineConfig({...base, cacheDir: '.goose/out/deepseek-capture-vite-cache', test: {...base.test,
  include: ['scripts/oracles/deepseek_capture.probe.spec.ts'], exclude: [], testTimeout: 60000}})
