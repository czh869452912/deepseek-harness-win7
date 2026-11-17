import { AjvJsonSchemaValidator } from '@sdk/validator'
const provider = new AjvJsonSchemaValidator()
export function observe(operation: any) {
  let validator
  try { validator = provider.getValidator(operation.schema) }
  catch (error) { return { compiled: false, message: error instanceof Error ? error.message : String(error) } }
  return operation.compileOnly ? { compiled: true } : { compiled: true, ...validator(operation.value) }
}
