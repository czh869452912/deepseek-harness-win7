import { readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve, join } from 'node:path'
import { pathToFileURL } from 'node:url'

const sdkRoot = resolve(process.argv[2])
const source = await import(pathToFileURL(join(sdkRoot,'dist/esm/types.js')).href)
const packageInfo = JSON.parse(readFileSync(join(sdkRoot,'package.json'),'utf8'))
if (packageInfo.version !== '1.29.0') throw new Error('MCP schema export requires pinned SDK 1.29.0')
const predicates = new Set()
const kinds = new Set()
function exportSchema(schema) {
  const definition = schema._zod.def
  kinds.add(definition.type)
  const node = {type:definition.type}
  switch (definition.type) {
    case 'object':
      node.shape = Object.fromEntries(Object.entries(definition.shape).map(([name,value]) => [name,exportSchema(value)]))
      if (definition.catchall) node.catchall = exportSchema(definition.catchall)
      break
    case 'optional': case 'nullable':
      node.inner = exportSchema(definition.innerType)
      break
    case 'array':
      node.element = exportSchema(definition.element)
      break
    case 'record':
      node.key = exportSchema(definition.keyType)
      node.value = exportSchema(definition.valueType)
      break
    case 'union':
      node.options = definition.options.map(exportSchema)
      break
    case 'intersection':
      node.left = exportSchema(definition.left)
      node.right = exportSchema(definition.right)
      break
    case 'literal':
      node.values = definition.values
      break
    case 'enum':
      node.values = Object.values(definition.entries)
      break
    case 'number':
      if (definition.format) node.format = definition.format
      node.checks = (definition.checks ?? []).map(check => check._zod.def)
      break
    case 'custom': {
      const predicate = String(definition.fn)
      predicates.add(predicate)
      if (predicate !== "(v) => v !== null && (typeof v === 'object' || typeof v === 'function')") throw new Error('Unreviewed custom MCP predicate: '+predicate)
      node.type = 'assert-object'
      break
    }
    case 'unknown': case 'string': case 'boolean': case 'never':
      break
    default: throw new Error('Unsupported MCP schema kind: '+definition.type)
  }
  return node
}
const names = ['JSONRPCMessageSchema','InitializeResultSchema','ListToolsResultSchema','ToolListChangedNotificationSchema']
const schemas = Object.fromEntries(names.map(name => [name,exportSchema(source[name])]))
const sourceHash = createHash('sha256').update(readFileSync(join(sdkRoot,'dist/esm/types.js'))).digest('hex')
writeFileSync(process.argv[3],JSON.stringify({sdkVersion:packageInfo.version,schemaSourceSha256:sourceHash,
  kinds:[...kinds].sort(),predicates:[...predicates],schemas},null,2)+'\n')
