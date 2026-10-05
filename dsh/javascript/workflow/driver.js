const sourceListeners = []
const sourcePort = {
  on(name, callback) {
    if (name === 'message') sourceListeners.push(callback)
  },
  postMessage(message) {
    if (message.type === 'result') message = { type: 'terminal', result: message.result }
    __emit(encodeSource(message))
  },
}

function encodeSource(value) {
  if (typeof value === 'number' && Object.is(value, -0)) return '-0.0'
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(encodeSource).join(',') + ']'
  return '{' + Object.keys(value).map(key => JSON.stringify(key) + ':' + encodeSource(value[key])).join(',') + '}'
}

const sourceSession = __workflowSource.runWorkerSession(sourcePort, {
  meta: __request.meta, body: __request.body, args: __request.args, limits: __request.limits,
})
globalThis.__receive = message => sourceListeners.forEach(callback => callback(message))
globalThis.__drive = () => sourceSession
