import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
export default defineConfig({...base,test:{...base.test,include:[
  'reference/packages/web/web-search-deepseek/tests/deepseek.spec.ts',
  'reference/packages/web/web-search-deepseek/tests/settings.spec.ts',
  'reference/packages/web/web-search-deepseek/tests/redirect.spec.ts',
]}})
