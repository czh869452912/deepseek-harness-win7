import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'

export default defineConfig({...base,test:{...base.test,include:[
  'reference/packages/core/agent-loop/tests/tool-calls.spec.ts',
  'reference/packages/core/agent-loop/tests/settings.spec.ts',
]}})
