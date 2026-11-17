/** Pure upstream projector carrier. No plugin validator or transform is invoked. */
export { createConfigProjector, LOADER_EXPRESSION_SCHEMA } from '@projection/projector'
export { createConfigProjector as createAsyncConfigProjector } from '@projection/async-projector'

/** Decode the private graph transport, preserving aliases, cycles and undefined. */
export function decodeGraph(wire: any): any[] {
  return createGraphState().merge(wire)
}

/** Update object contents while retaining identities held by a suspended visit. */
export function createGraphState(onBuilder?: (index: number) => any): any {
  const values: any[] = []
  const allocate = (record: any) => {
    switch (record.kind) {
      case 'array': return []
      case 'object': return {}
      case 'opaque': return Object.create({ opaque: true })
      case 'schema': return { [Symbol.for('schemastery')]: true }
      case 'date': return new Date(record.value)
      case 'regexp': return new RegExp(record.source, record.flags)
      case 'function': return () => { throw new Error('opaque callback must not execute') }
      default: throw new Error('invalid graph record kind')
    }
  }
  const decode = (item: any): any => {
    if (item === null || typeof item !== 'object') return item
    if (Object.hasOwn(item, 'ref')) {
      if (!Number.isInteger(item.ref) || item.ref < 0 || item.ref >= values.length) throw new Error('invalid graph reference')
      return values[item.ref]
    }
    switch (item.atom) {
      case 'undefined': return undefined
      case 'nan': return NaN
      case 'infinity': return Infinity
      case '-infinity': return -Infinity
      case 'bigint': return BigInt(item.value)
      case 'symbol': return Symbol(item.value)
      default: throw new Error('invalid graph atom')
    }
  }
  const merge = (wire: any) => {
   while (values.length < wire.heap.length) values.push(allocate(wire.heap[values.length]))
   wire.heap.forEach((record: any, index: number) => {
    const value = values[index]
    if (record.kind === 'array') { value.length = 0; for (const item of record.items) value.push(decode(item)) }
    if (record.kind === 'object' || record.kind === 'schema') {
      for (const key of Object.keys(value)) delete value[key]
      for (const [key, item] of record.entries) {
        Object.defineProperty(value, key, { value: decode(item), writable: true, enumerable: true, configurable: true })
      }
    }
    if (record.kind === 'schema' && record.builder !== undefined) {
      value.builder = () => {
        if (record.builder.deferred === true) {
          if (!onBuilder) throw new Error('live builder bridge unavailable')
          return onBuilder(index)
        }
        wire.builderCalls.push(index)
        if (Object.hasOwn(record.builder, 'error')) throw new Error(record.builder.error)
        return decode(record.builder)
      }
    }
  })
   return wire.roots.map(decode)
  }
  return {merge, decode}
}
