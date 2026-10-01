import { HarnessError } from '@deepseek-ai/dsh-llm'

export function build(spec: any): any {
  const nodes: Record<string, any> = {}
  for (const [identity, node] of Object.entries<any>(spec.nodes)) {
    let value: any
    if (node.type === 'error') value = new Error(node.message)
    else if (node.type === 'aggregate') value = new AggregateError([], node.message)
    else if (node.type === 'harness') value = new HarnessError(node.message, node.code)
    else if (node.type === 'value') value = node.special === 'undefined' ? undefined : node.value
    else {
      value = node.inheritedMessage === undefined ? {} : Object.create({ message: node.inheritedMessage })
      if ('message' in node) value.message = node.message
      if (node.coercion === 'throw') value.toString = () => { throw new Error('hostile coercion') }
      else if (node.coercion === 'primitive') value.toString = () => node.value
      else if (node.coercion === 'object') {
        value.toString = () => ({})
        if ('valueOf' in node) value.valueOf = () => node.valueOf
      }
    }
    if ('name' in node) value.name = node.name
    nodes[identity] = value
  }
  const resolve = (value: any) => value !== null && typeof value === 'object' && 'ref' in value ? nodes[value.ref] : value
  for (const [identity, node] of Object.entries<any>(spec.nodes)) {
    if ('cause' in node) nodes[identity].cause = resolve(node.cause)
    if (node.type === 'aggregate') nodes[identity].errors = node.errors.map(resolve)
    for (const field of node.hostile ?? []) Object.defineProperty(nodes[identity], field, {
      get() { throw new Error('hostile getter') }, configurable: true,
    })
  }
  return nodes[spec.root]
}
