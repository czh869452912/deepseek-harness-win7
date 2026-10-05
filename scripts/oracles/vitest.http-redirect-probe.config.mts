import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.deepseek-probe.config.mts'
export default defineConfig({...base,test:{...base.test,include:['scripts/oracles/http_redirect.probe.spec.ts']}})
