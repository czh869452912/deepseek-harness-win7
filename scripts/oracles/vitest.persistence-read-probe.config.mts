import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'

export default defineConfig({...base,test:{...base.test,
  include:['scripts/oracles/persistence_public.probe.spec.ts','scripts/oracles/persistence_order.probe.spec.ts'],
  exclude:[],testTimeout:20000}})
