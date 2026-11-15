// Native carrier only: the Workflow Guest above remains upstream bytes.
const workflowPending = new Map()
let workflowNext = 0
function workflowCall(name, value) {
  const id = ++workflowNext
  return new Promise((resolve, reject) => {
    workflowPending.set(id, {resolve, reject})
    __emit(JSON.stringify({type: 'binding', id, name, value}))
  })
}
const workflowHost = {}
for (const name of ['begin', 'startChild', 'childResult', 'disposeChild', 'progress']) {
  workflowHost[name] = value => workflowCall(name, value)
}
globalThis.__receive = message => {
  if (message.type === 'go') return
  if (message.type !== 'binding-result') throw new Error('unexpected workflow carrier message')
  const pending = workflowPending.get(message.id)
  if (!pending) throw new Error('unknown workflow binding reply')
  workflowPending.delete(message.id)
  if ('error' in message) pending.reject(new Error(message.error))
  else pending.resolve(message.value)
}
globalThis.__drive = async () => {
  const result = await runWorkflowGuest(workflowHost)
  __emit(JSON.stringify({type: 'terminal', result}))
}
__emit(JSON.stringify({type: 'ready'}))
