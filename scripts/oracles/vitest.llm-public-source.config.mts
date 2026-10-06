import {defineConfig} from './official/node_modules/vitest/dist/config.js'
import base from './vitest.agent-lifecycle.config.mts'
import {fileURLToPath} from 'node:url'

export default defineConfig({...base,cacheDir:'.goose/out/llm-public-source-vite-cache',resolve:{alias:[...base.resolve!.alias as any[],{find:/^fast-check$/,replacement:fileURLToPath(new URL('./official/node_modules/fast-check/lib/fast-check.js',import.meta.url))}]},test:{...base.test,include:['reference/packages/llm/llm/tests/**/*.spec.ts'],exclude:[],testTimeout:20000}})
