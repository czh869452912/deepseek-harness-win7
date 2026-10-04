import { existsSync } from 'node:fs'
import { Context } from '@deepseek-ai/cordis'
import { LocalSubprocessRuntime } from '../../reference/packages/subprocess/subprocess-local/src/index.ts'

const [workspace, trigger, python, peer] = process.argv.slice(2)
const context = new Context()
const fiber = await context.plugin(LocalSubprocessRuntime)
const controller = new AbortController()
const handle = context.subprocess.spawn({argv: [python!, peer!, 'root', workspace + '/tree.json'], cwd: workspace!,
  stdio: {stdin: 'ignore', stdout: {maxBytes: 1024}, stderr: {maxBytes: 1024}}, graceMs: 100, signal: controller.signal})
while (!existsSync(workspace + '/proceed')) await new Promise(resolve => setTimeout(resolve, 10))
if (trigger === 'dispose' || trigger === 'abort' || trigger === 'terminate') {
  if (trigger === 'dispose') await fiber.dispose()
  else {
    if (trigger === 'abort') controller.abort('explicit tree cancellation')
    else handle.terminate()
    await handle.done
    await handle.waitForExit()
    await fiber.dispose()
  }
  process.exit(0)
}
if (trigger === 'direct') process.exit(23)
setImmediate(() => {throw new Error('host-exit-uncaught-exception')})
await new Promise(() => {})
