import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.deepseek-probe.config.mts'

export default defineConfig({...base,cacheDir:'.goose/out/javascript-errors-vite-cache',test:{...base.test,include:['scripts/oracles/javascript_errors_*.probe.spec.ts'],exclude:[],testTimeout:20000}})
