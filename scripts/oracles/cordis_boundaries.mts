import { Context } from '../../reference/vendor/cordis/src/index.ts'
export async function scenario(id: number) {
  const ctx = new Context(), log: string[] = []
  let release!: () => void
  const done = new Promise<void>(resolve => release = resolve)
  ctx.on('event', async () => {
    log.push('prefix')
    await Promise.resolve()
    log.push('tail')
    release()
  })
  ctx.on('event', () => { log.push('peer') })
  ctx.emit('event')
  const immediate = [...log]
  await done
  await ctx.fiber.dispose()
  return { immediate, log }
}
