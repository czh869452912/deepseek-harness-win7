class Script {
  constructor(source, options) {
    if (globalThis.__compiledParseError) throw globalThis.__compiledParseError
    if (source !== '(async () => {\n' + globalThis.__request.body + '\n})()') {
      throw new Error('owned workflow wrapper differs')
    }
    this.options = options
  }

  runInContext(context, options) {
    return globalThis.__runCompiled(context, options)
  }
}

function createContext(values, options) {
  return values
}

const vm = {Script, createContext}
