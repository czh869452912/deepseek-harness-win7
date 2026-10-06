import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.deepseek-probe.config.mts'

export default defineConfig({...base,cacheDir:'.goose/out/canonical-llm-vite-cache',test:{...base.test,include:['scripts/oracles/canonical_llm_*.probe.spec.ts'],exclude:[],testTimeout:20000}})
