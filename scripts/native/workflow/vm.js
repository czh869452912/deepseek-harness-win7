export class Script {
  constructor(source, options) {
    if (source !== '(async () => {\n' + globalThis.__request.body + '\n})()') {
      throw new Error('owned workflow wrapper differs')
    }
    this.options = options
  }

  runInContext(context, options) {
    return globalThis.__runCompiled(context, options)
  }
}

export function createContext(values, options) {
  return values
}
