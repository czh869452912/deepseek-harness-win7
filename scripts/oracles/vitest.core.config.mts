import { defineConfig } from './official/node_modules/vitest/dist/config.js'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../../', import.meta.url))
export default defineConfig({
  root,
  resolve: { alias: {
    '@deepseek-ai/cordis': root + 'reference/vendor/cordis/src/index.ts',
    '@deepseek-ai/cordis-plugin-loader': root + 'reference/vendor/loader/src/index.ts',
    '@deepseek-ai/cordis-plugin-hmr': root + 'reference/vendor/hmr/src/index.ts',
    '@deepseek-ai/cordis-plugin-timer': root + 'reference/vendor/timer/src/index.ts',
    '@deepseek-ai/schemastery': root + 'reference/vendor/schemastery/src/index.ts',
    'chokidar': root + 'scripts/oracles/node_modules/chokidar/index.js',
    'picomatch': root + 'scripts/oracles/node_modules/picomatch/index.js',
    '@babel/code-frame': root + 'scripts/oracles/node_modules/@babel/code-frame/lib/index.js',
    '@deepseek-ai/cosmokit': root + 'reference/vendor/cosmokit/src/index.ts',
    'vitest': fileURLToPath(new URL('./official/node_modules/vitest/dist/index.js', import.meta.url)),
  } },
  test: { include: ['reference/packages/extensions/tool-cordis/tests/cordis-lifecycle.spec.ts', 'reference/packages/boot/app-boot/tests/hmr-config.spec.ts'],
          pool: 'forks', execArgv: ['--expose-internals'], maxWorkers: 1, fileParallelism: false },
})
