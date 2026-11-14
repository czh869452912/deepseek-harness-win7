/** Observe the unchanged fixed Source helpers; no copied implementation. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const [source, corpus] = process.argv.slice(2)
const base = resolve(source!, 'packages/session/session-format-v3-to-v4/src')
const modules = await Promise.all(['tool-role', 'sources', 'content', 'developer', 'system-message',
  'message-sources', 'retired-syntax', 'facts', 'fork-result', 'references',
  'extension-identities', 'validation', 'relationships', 'migration', 'codec'].map(name => import(pathToFileURL(resolve(base, name + '.ts')).href)))
const functions = Object.assign({}, ...modules)
for (const name of ['restoreReleasedV4Artifact', 'assertReleasedV4Relationships', 'assertV4LifecycleRelationships', 'assertV4RowAdmission']) {
  const original = functions[name]
  functions[name] = (value: any, known?: string[]) => original(value, known === undefined ? undefined : new Set(known))
}
functions.v4DecodeHeader = (value: any) => functions.releasedV4SessionFormatCodec.decodeHeader(value)
functions.v4EncodeHeader = (header: any, cut: number) => functions.releasedV4SessionFormatCodec.encodeHeader(header, cut)
functions.v4EncodeEvent = (event: any) => functions.releasedV4SessionFormatCodec.encodeEvent(event)
functions.migrateV3Stage = (input: any, children: any[], events: any[], unbound = false, runs = false) => {
  const declaration = unbound ? functions.sessionFormatV3ToV4 : functions.createSessionFormatV3ToV4(children)
  const emitted: any[] = []
  const result: any = { events: emitted }
  try {
    result.header = declaration.migrateHeader(input.sourceHeader)
    const stage = declaration.createStage(input)
    const context = { emitEvent: (event: any) => emitted.push(event), emitRun: (run: any) => emitted.push(...run.expand()) }
    if (runs) stage.transformRun({ expand: () => events }, context)
    else for (const event of events) stage.transformEvent(event, context)
    result.inheritedEventCount = stage.finish(context)
    if (stage.headerInheritedEventCount !== undefined) result.headerInheritedEventCount = stage.headerInheritedEventCount
  } catch (error: any) { result.error = { name: error.name, message: error.message } }
  return result
}
functions.v4DecodeRows = (header: any, rows: any[], recovery: string) => {
  const emitted: any[] = [], result: any = { events: emitted }
  try {
    const decoder = functions.releasedV4SessionFormatCodec.createDecoder(header, recovery)
    result.header = decoder.header
    const context = { emitEvent: (event: any) => emitted.push(event), emitRun: (run: any) => emitted.push(...run.expand()) }
    for (const row of rows) decoder.decodeRow(row, context)
    result.inheritedEventCount = decoder.finish(context)
  } catch (error: any) { result.error = { name: error.name, message: error.message } }
  return result
}
const rows = JSON.parse(readFileSync(corpus!, 'utf8'))
const result = rows.map((row: any) => {
  const before = JSON.stringify(row.args)
  try {
    const value = functions[row.operation](...row.args)
    return { case: row.case, ok: true, value: value ?? null,
      same: value === row.args[0], unchanged: before === JSON.stringify(row.args),
      serialized: JSON.stringify(value ?? null) }
  } catch (error: any) {
    return { case: row.case, ok: false, name: error.name, message: error.message,
      unchanged: before === JSON.stringify(row.args) }
  }
})
process.stdout.write(JSON.stringify(result))
