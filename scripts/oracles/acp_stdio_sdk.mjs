import {Connection, RequestError, Handled} from './official/node_modules/@agentclientprotocol/sdk/dist/jsonrpc.js';
import {ndJsonStream} from './official/node_modules/@agentclientprotocol/sdk/dist/stream.js';
import * as schemas from './official/node_modules/@agentclientprotocol/sdk/dist/schema/zod.gen.js';
import {readFileSync, writeFileSync} from 'node:fs';
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
async function framing() {

const tick = () => new Promise(resolve => setImmediate(resolve))
async function settled() { for (let iteration = 0; iteration < 100; iteration++) await tick() }
const observations = []
for (const mode of ['frames', 'errors', 'batch', 'responses', 'cancel', 'duplicate', 'eof', 'tail', 'eof-parse', 'eof-request']) {
  const output = []
  const active = []
  let controller
  const input = new ReadableStream({ start(value) { controller = value } })
  const stream = ndJsonStream(new WritableStream({ write(bytes) { output.push(JSON.parse(new TextDecoder().decode(bytes))) } }), input)
  const push = value => controller.enqueue(new TextEncoder().encode(value))
  if (mode === 'tail') {
    const messages = []
    const reading = (async () => { for await (const message of stream.readable) messages.push(message) })()
    push('\n{"jsonrpc":"2.0","id":1,"method":"echo","params":"中文😀"}')
    controller.close()
    await reading
    observations.push({ mode, output, messages })
    continue
  }
  const connection = new Connection(stream, [{ async handleMessage(message) {
    if (message.kind !== 'request') return Handled.no(message)
    if (message.method === 'echo') { await message.responder.respond(message.params ?? null); return Handled.yes() }
    if (message.method === 'plain') throw new Error('fixture failure')
    if (message.method === 'invalid') throw RequestError.invalidParams(undefined, 'bad session')
    if (message.method === 'internal') throw RequestError.internalError(undefined, 'turn failed')
    if (message.method === 'wait') {
      let release
      const completion = new Promise((resolve, reject) => {
        release = resolve
        message.signal.addEventListener('abort', () => reject(message.signal.reason), { once: true })
      })
      active.push({ signal: message.signal, release })
      const value = await completion
      await message.responder.respond(value)
      return Handled.yes()
    }
    return Handled.no(message)
  } }])
  if (mode === 'frames') {
    const bytes = new TextEncoder().encode('\n{\n42\nnull\n{"foo":"bar"}\n{"jsonrpc":"2.0","id":true,"method":"echo"}\n{"jsonrpc":"2.0","id":null,"method":"echo","params":"中文😀"}\n')
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
    await settled()
  } else if (mode === 'errors') {
    for (const method of ['unknown', 'plain', 'invalid', 'internal']) {
      push(JSON.stringify({ jsonrpc: '2.0', id: method, method }) + '\n')
      await settled()
    }
  } else if (mode === 'batch') {
    push(JSON.stringify([{ jsonrpc: '2.0', id: 1, method: 'echo', params: { value: '中文' } }, 42,
      { jsonrpc: '2.0', method: 'unknown-notification' }, { jsonrpc: '2.0', id: 2, method: 'unknown' },
      { jsonrpc: '2.0', id: 3, result: 'wrong direction' }]) + '\n')
    await settled()
    push('[]\n')
    await settled()
  } else if (mode === 'responses') {
    for (const value of [{ id: 'unknown' }, { jsonrpc: '2.0', id: 'unknown', result: 'ignored' },
      [{ jsonrpc: '2.0', id: 'unknown', result: 'ignored' }, { id: 'bad', error: {} }]]) push(JSON.stringify(value) + '\n')
    await settled()
  } else if (mode === 'cancel' || mode === 'duplicate') {
    push('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
    await settled()
    if (mode === 'duplicate') {
      push('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
      await settled()
    }
    push('{"jsonrpc":"2.0","method":"$/cancel_request","params":{"requestId":"1"}}\n')
    await settled()
    const wrongTypeAborted = active.some(value => value.signal.aborted)
    push('{"jsonrpc":"2.0","method":"$/cancel_request","params":{"requestId":1}}\n')
    await settled()
    const cancelled = active.map(value => value.signal.aborted)
    if (mode === 'duplicate') { active[0].release('first completed'); await settled() }
    observations.push({ mode, output, wrongTypeAborted, cancelled })
    connection.close()
    continue
  } else if (mode === 'eof-parse' || mode === 'eof-request') {
    push(mode === 'eof-parse' ? '{' : '{"jsonrpc":"2.0","id":7,"method":"echo","params":"tail"}')
    controller.close()
    await connection.closed
    await settled()
    observations.push({mode, output})
    continue
  } else {
    push('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
    await settled()
    controller.close()
    await connection.closed
    await settled()
    observations.push({ mode, output, aborted: active[0].signal.aborted })
    continue
  }
  observations.push({ mode, output })
  connection.close()
}
return observations;
}

async function outgoing() {

const observations = [];
const settled = async () => {for (let iteration = 0; iteration < 30; iteration++) await new Promise(resolve => setImmediate(resolve));};
for (const mode of ['result', 'remote-error', 'invalid', 'unknown', 'preabort', 'cancel', 'close', 'write-failure', 'mapper']) {
  const output = [];
  let input;
  const readable = new ReadableStream({start(controller) {input = controller;}});
  const writable = new WritableStream({write(bytes) {
    output.push(JSON.parse(new TextDecoder().decode(bytes)));
    if (mode === 'write-failure') throw new Error('write fixture failure');
  }});
  const connection = new Connection(ndJsonStream(writable, readable), []);
  const push = value => input.enqueue(new TextEncoder().encode(JSON.stringify(value) + '\n'));
  const controller = new AbortController();
  if (mode === 'preabort') controller.abort('fixture cancellation');
  let outcome;
  const pending = connection.sendRequest('fixture/request', {value: '中文'},
    mode === 'mapper' ? () => {throw new Error('mapper fixture failure');} : value => ({mapped: value}),
    {cancellationSignal: controller.signal}).then(value => {outcome = {value};}, error => {
      outcome = {error: {message: error.message, ...(error.code === undefined ? {} : {code: error.code}),
        ...(error.data === undefined ? {} : {data: error.data})}};
    });
  await settled();
  if (mode === 'cancel') {controller.abort('fixture cancellation'); await settled();}
  if (mode === 'unknown') {push({jsonrpc: '2.0', id: '0', result: 'ignored'}); await settled();}
  const settledBeforeReply = outcome !== undefined;
  if (mode === 'close') input.close();
  else if (mode !== 'write-failure') push(mode === 'remote-error'
    ? {jsonrpc: '2.0', id: 0, error: {code: -32602, message: 'fixture rejected', data: {value: false}}}
    : mode === 'invalid' ? {jsonrpc: '2.0', id: 0, result: 'ambiguous', error: {code: -32603, message: 'invalid'}}
    : {jsonrpc: '2.0', id: 0, result: 'accepted'});
  await pending;
  await settled();
  observations.push({mode, output, settledBeforeReply, outcome, closed: connection.signal.aborted});
  connection.close();
}
return observations;
}

async function bytes() {

const observations = [];
for (const {mode, bytes} of cases.bytes) {
  const output = [];
  let input;
  const readable = new ReadableStream({start(controller) {input = controller;}});
  const writable = new WritableStream({write(frame) {output.push(JSON.parse(new TextDecoder().decode(frame)));}});
  const connection = new Connection(ndJsonStream(writable, readable), [{async handleMessage(message) {
    if (message.kind !== 'request' || message.method !== 'echo') return Handled.no(message);
    await message.responder.respond(message.params ?? null);
    return Handled.yes();
  }}]);
  for (const byte of Buffer.from(bytes, 'base64')) input.enqueue(new Uint8Array([byte]));
  for (let iteration = 0; iteration < 100; iteration++) await new Promise(resolve => setImmediate(resolve));
  input.close();
  await connection.closed;
  for (let iteration = 0; iteration < 20; iteration++) await new Promise(resolve => setImmediate(resolve));
  observations.push({mode, output});
}
return observations;
}

const names = {
  initialize: 'zInitializeRequest', authenticate: 'zAuthenticateRequest',
  'session/new': 'zNewSessionRequest', 'session/list': 'zListSessionsRequest',
  'session/resume': 'zResumeSessionRequest', 'session/close': 'zCloseSessionRequest',
  'session/set_config_option': 'zSetSessionConfigOptionRequest', 'session/prompt': 'zPromptRequest',
  'session/cancel': 'zCancelNotification',
};
const observations = [];
for (const [section, rows] of [['framing', await framing()], ['outgoing', await outgoing()], ['bytes', await bytes()]])
  for (const row of rows) observations.push({...row, mode: section + '/' + row.mode});
for (const {mode, method, params} of [...cases.parameters, ...cases.fuzz]) {
  try {observations.push({mode: 'params/' + mode, value: schemas[names[method]].parse(params)});}
  catch (error) {observations.push({mode: 'params/' + mode, error: {code: -32602, message: 'Invalid params', data: error.format()}});}
}
writeFileSync(process.argv[3], JSON.stringify(observations, null, 2) + '\n');
