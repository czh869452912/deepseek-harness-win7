import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'

export default defineConfig({...base, cacheDir:'.goose/out/permission-presets-vite-cache',
  test:{...base.test,include:['scripts/oracles/permission_presets*.probe.spec.ts'],exclude:[]}})
