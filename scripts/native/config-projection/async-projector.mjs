/** Sequential async adaptation solely for crossing the Python lazy-builder bridge.
 * Every replacement must match the fixed upstream text exactly once.
 * Container visits retain their original order; no Promise.all is introduced.
 */
export function asyncProjector(source) {
  const replace = (before, after) => {
    if (source.split(before).length !== 2) throw new Error('Config async adaptation context differs: ' + before)
    source = source.replace(before, after)
  }
  replace('Promise<(root: NativeConfigSchema, prefix: string) => ConfigProjection>',
    'Promise<(root: NativeConfigSchema, prefix: string) => Promise<ConfigProjection>>')
  replace('return (root, prefix) => {', 'return async (root, prefix) => {')
  replace('const visit = (node: NativeConfigSchema, path: string, strict = false): NodeProjection => {',
    'const visit = async (node: NativeConfigSchema, path: string, strict = false): Promise<NodeProjection> => {')
  replace('next = Reflect.apply(inner.builder, inner, [])', 'next = await Reflect.apply(inner.builder, inner, [])')
  replace('projection = looseProjection ?? visit({ ...inner, meta }, `${path}/lazy`, strict)',
    'projection = looseProjection ?? await visit({ ...inner, meta }, `${path}/lazy`, strict)')
  replace('const child = (value: NativeConfigSchema | undefined, suffix: string, childStrict = false): NodeProjection => {',
    'const child = async (value: NativeConfigSchema | undefined, suffix: string, childStrict = false): Promise<NodeProjection> => {')
  replace('const result = visit(value, `${path}/${suffix}`, childStrict)', 'const result = await visit(value, `${path}/${suffix}`, childStrict)')
  replace(`const properties = Object.fromEntries(Object.entries(node.dict ?? {}).map(([key, field]) => {
              const value = child(field, key)
              if (value.acceptsMissing === false) required.push(key)
              return [key, value.schema]
            }))`, `const properties: Record<string, InputSchema> = {}
            for (const [key, field] of Object.entries(node.dict ?? {})) {
              const value = await child(field, key)
              if (value.acceptsMissing === false) required.push(key)
              Object.defineProperty(properties, key, {value: value.schema, enumerable: true, writable: true, configurable: true})
            }`)
  replace("const item = child(node.inner, 'items')", "const item = await child(node.inner, 'items')")
  replace("const valueSchema = child(node.inner, 'values').schema", "const valueSchema = (await child(node.inner, 'values')).schema")
  replace("const key = child(node.sKey, 'keys')", "const key = await child(node.sKey, 'keys')")
  replace('const values = node.list.map((item, index) => child(item, String(index)))',
    'const values: NodeProjection[] = []; for (const [index, item] of node.list.entries()) values.push(await child(item, String(index)))')
  replace('const variants = node.list.map((item, index) => child(item, String(index), strict))',
    'const variants: NodeProjection[] = []; for (const [index, item] of node.list.entries()) variants.push(await child(item, String(index), strict))')
  replace("core = child(node.inner, 'input', true).schema", "core = (await child(node.inner, 'input', true)).schema")
  replace("const result = visit(root, 'config')", "const result = await visit(root, 'config')")
  return source
}
