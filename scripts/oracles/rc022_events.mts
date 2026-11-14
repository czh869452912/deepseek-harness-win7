/** Observe actual fixed Cordis dispatch without copying its implementation. */
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const { Context } = await import(pathToFileURL(resolve(process.argv[2]!, 'vendor/cordis/src/context.ts')).href)
const ctx = new Context(), result: any = {}, trace: string[] = [], held: any[] = []
ctx.on('chain', (value: string, next: () => string) => {
  held.push(next); trace.push('outer')
  const answer = next()
  try { next() } catch (error: any) { result.repeat = error.message }
  return answer + '-outer'
})
ctx.on('chain', (value: string, next: () => string) => {
  result.independent = next !== held[0]; trace.push('inner'); return next() + '-inner'
})
result.value = ctx.waterfall('chain', 'input', () => 'end')
result.trace = trace
try { held[0]() } catch (error: any) { result.late = error.message }
const left = Symbol('same'), right = Symbol('same'), calls: any[] = [], observed: any[] = []
ctx.on('internal/dispatch', (mode: string, name: any, args: any[]) => observed.push([mode, name === left ? 'left' : 'right', args]))
ctx.on(left, (value: number) => calls.push(['left', value]))
ctx.on(right, (value: number) => calls.push(['right', value]))
await ctx.parallel(left, 2); ctx.emit(right, 3)
result.calls = calls; result.observed = observed
result.disposal = []
for (const key of ['__proto__', 'constructor', 'toString', Symbol('once')]) {
  let count = 0
  const dispose = ctx.once(key, () => { count++ })
  ctx.emit(key); ctx.emit(key)
  result.disposal.push({ count, retained: Object.hasOwn(ctx.events._hooks, key), again: dispose() ?? null })
}
await ctx.fiber.dispose()
process.stdout.write(JSON.stringify(result))
