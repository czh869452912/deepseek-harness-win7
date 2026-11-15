// Host-only substrate adapter; headless.js and serialize.js remain unchanged.
globalThis.process = { title: 'dsh-terminal-screen' }
globalThis.self = globalThis
globalThis.console = { log() {}, warn() {}, error() {} }
// Every write is applied through xterm's synchronous parser inside an ordered
// host operation. Browser painting/blink and the asynchronous write timer are unused.
globalThis.setTimeout = () => 0
globalThis.clearTimeout = () => {}
globalThis.setInterval = () => 0
globalThis.clearInterval = () => {}

function commonJS(source) {
  return Function('const exports = {}; const module = { exports };\n' + source + '\nreturn module.exports;')()
}
const { Terminal } = commonJS(__request.headless)
const { SerializeAddon } = commonJS(__request.serializer)
const terminal = new Terminal({ ...__request.options, allowProposedApi: true })
const serializer = new SerializeAddon()
terminal.loadAddon(serializer)
const markers = new Map()

function state() {
  const buffer = terminal.buffer.active
  const lines = []
  for (let index = 0; index < buffer.length; index++) {
    const row = buffer.getLine(index)
    lines.push({ text: row.translateToString(false), trimmed: row.translateToString(true), isWrapped: row.isWrapped })
  }
  return {
    buffer: { type: buffer.type, baseY: buffer.baseY, cursorY: buffer.cursorY, lines },
    markers: [...markers].map(([id, value]) => ({ id, type: value.type, present: value.marker !== undefined,
      ...value.marker === undefined ? {} : { line: value.marker.line, disposed: value.marker.isDisposed } })),
  }
}

globalThis.__receive = message => {
  if (message.type === 'go') { __emit(JSON.stringify({ type: 'screen-state', ...state() })); return }
  if (message.type === 'cancel') {
    terminal.dispose()
    __emit(JSON.stringify({ type: 'terminal', result: { disposed: true } }))
    return
  }
  if (message.type !== 'screen') throw Error('Invalid screen operation')
  try {
    switch (message.operation) {
      case 'write': terminal._core.writeSync(message.data); break
      case 'resize': terminal.resize(message.cols, message.rows); break
      case 'mark': {
        const buffer = terminal.buffer.active
        let row = buffer.baseY + buffer.cursorY
        while (row > 0 && buffer.getLine(row).isWrapped) row--
        const marker = terminal.registerMarker(row - buffer.baseY - buffer.cursorY)
        markers.set(message.marker, { marker, type: buffer.type })
        break
      }
      case 'unmark': markers.get(message.marker)?.marker?.dispose(); markers.delete(message.marker); break
      case 'snapshot': break
      default: throw Error('Unknown screen operation')
    }
    __emit(JSON.stringify({ type: 'screen-result', request: message.request, ...state(),
      ...message.operation === 'snapshot' ? { snapshot: serializer.serialize() } : {} }))
  } catch (error) {
    __emit(JSON.stringify({ type: 'screen-result', request: message.request, error: String(error) }))
  }
}
globalThis.__drive = () => new Promise(() => {})
__emit(JSON.stringify({ type: 'ready' }))
