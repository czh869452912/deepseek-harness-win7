import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.acp.config.mts'

export default defineConfig({...base,test:{...base.test,include:['scripts/oracles/mcp_factory_failure.probe.spec.ts']}})
