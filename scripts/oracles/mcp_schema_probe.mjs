import { readFileSync, writeFileSync } from 'node:fs'
import { resolve, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const sdkRoot = resolve(process.argv[2])
const source = await import(pathToFileURL(join(sdkRoot, 'dist/esm/types.js')).href)
const definitions = JSON.parse(readFileSync(process.argv[3], 'utf8'))
function sample(schema) {
  switch (schema.type) {
    case 'optional': return sample(schema.inner)
    case 'string': return 'controlled'
    case 'number': return 1
    case 'boolean': return true
    case 'unknown': return {preserved: true}
    case 'assert-object': return {}
    case 'literal': case 'enum': return schema.values[0]
    case 'array': return [sample(schema.element)]
    case 'record': return {extension: sample(schema.value)}
    case 'object': return Object.fromEntries(Object.entries(schema.shape).map(([name, field]) => [name, sample(field)]))
    case 'union': return sample(schema.options[0])
    default: throw new Error('Unsupported source sample: ' + schema.type)
  }
}
function paths(schema, prefix = []) {
  const result = [prefix]
  if (schema.type === 'optional') return paths(schema.inner, prefix)
  if (schema.type === 'object') for (const [name, field] of Object.entries(schema.shape)) result.push(...paths(field, [...prefix, name]))
  if (schema.type === 'array') result.push(...paths(schema.element, [...prefix, 0]))
  if (schema.type === 'record') result.push(...paths(schema.value, [...prefix, 'extension']))
  if (schema.type === 'union') result.push(...paths(schema.options[0], prefix))
  return result
}
const observations = []
function observe(name, label, value) {
  const parsed = source[name].safeParse(value)
  observations.push({name, label, value, result: parsed.success ? {data: parsed.data} : {issues: parsed.error.issues, message: parsed.error.message}})
}
for (const [name, schema] of Object.entries(definitions.schemas)) {
  const baseline = sample(schema)
  observe(name, 'complete', baseline)
  const unique = new Map(paths(schema).map(path => [JSON.stringify(path), path]))
  for (const path of unique.values()) {
    for (const [label, replacement] of Object.entries({null: null, boolean: false, integer: 1, fractional: 1.5,
      unsafe: 9007199254740992, string: 'invalid', array: [], object: {}, prototype: JSON.parse('{"__proto__":{},"2":null,"1":false,"extension":false}')})) {
      const value = structuredClone(baseline)
      if (!path.length) observe(name, label + ':' + JSON.stringify(path), replacement)
      else {
        let target = value
        for (const name of path.slice(0, -1)) target = target[name]
        target[path.at(-1)] = replacement
        observe(name, label + ':' + JSON.stringify(path), value)
      }
    }
    if (path.length) {
      const value = structuredClone(baseline)
      let target = value
      for (const name of path.slice(0, -1)) target = target[name]
      delete target[path.at(-1)]
      if (!Array.isArray(target)) observe(name, 'missing:' + JSON.stringify(path), value)
    }
  }
}
for (const packet of [
  {jsonrpc: '2.0', method: 'ping', id: 1, extra: true},
  {jsonrpc: '2.0', method: 'ping', id: 1.5},
  {jsonrpc: '2.0', result: {}, id: 1},
  {jsonrpc: '2.0', error: {code: -32602, message: 'invalid', data: null}, id: 1},
  {jsonrpc: '2.0', error: {code: -32602, message: 'invalid'}},
  {jsonrpc: '2.0', method: 'notifications/tools/list_changed', params: {_meta: {progressToken: 9007199254740992}}},
]) observe('JSONRPCMessageSchema', 'wire:' + observations.length, packet)
writeFileSync(process.argv[4], JSON.stringify(observations, null, 2) + '\n')
