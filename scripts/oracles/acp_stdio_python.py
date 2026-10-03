import asyncio
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.acp.rpc import ABSENT, AcpRpc, RequestError
from dsh.acp.parameters import validate_params
from dsh.core.abort import AbortController
from dsh.cordis.json_text import stringify_json

cases = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))

async def settled():
    for iteration in range(100):
        await asyncio.sleep(0)

async def framing():
    observations = []
    for mode in ['frames', 'errors', 'batch', 'responses', 'cancel', 'duplicate', 'eof', 'tail', 'eof-parse', 'eof-request']:
        output, active = [], []
        rpc = AcpRpc(lambda frame: output.append(json.loads(frame)))
        def echo(params, signal):
            return None if params is ABSENT else params
        async def plain(params, signal):
            raise RuntimeError('fixture failure')
        async def invalid(params, signal):
            raise RequestError(-32602, 'Invalid params: bad session')
        async def internal(params, signal):
            raise RequestError(-32603, 'Internal error: turn failed')
        async def wait(params, signal):
            completion = asyncio.get_running_loop().create_future()
            signal.add_listener('abort', lambda reason: completion.set_exception(reason) if not completion.done() else None)
            active.append((signal, completion))
            return await completion
        rpc.handlers = dict(echo=echo, plain=plain, invalid=invalid, internal=internal, wait=wait)
        if mode == 'frames':
            for byte in '\n{\n42\nnull\n{"foo":"bar"}\n{"jsonrpc":"2.0","id":true,"method":"echo"}\n{"jsonrpc":"2.0","id":null,"method":"echo","params":"中文😀"}\n'.encode('utf-8'):
                rpc.data(bytes([byte]))
            await settled()
        elif mode == 'errors':
            for method in ['unknown', 'plain', 'invalid', 'internal']:
                rpc.data(json.dumps(dict(jsonrpc='2.0', id=method, method=method)) + '\n')
                await settled()
        elif mode == 'batch':
            rpc.data(json.dumps([dict(jsonrpc='2.0', id=1, method='echo', params={'value': '中文'}), 42,
                dict(jsonrpc='2.0', method='unknown-notification'), dict(jsonrpc='2.0', id=2, method='unknown'),
                dict(jsonrpc='2.0', id=3, result='wrong direction')]) + '\n')
            await settled()
            rpc.data('[]\n')
            await settled()
        elif mode == 'responses':
            for value in [{'id': 'unknown'}, dict(jsonrpc='2.0', id='unknown', result='ignored'),
                          [dict(jsonrpc='2.0', id='unknown', result='ignored'), {'id': 'bad', 'error': {}}]]:
                rpc.data(json.dumps(value) + '\n')
            await settled()
        elif mode in ('cancel', 'duplicate'):
            rpc.data('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
            await settled()
            if mode == 'duplicate':
                rpc.data('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
                await settled()
            rpc.data('{"jsonrpc":"2.0","method":"$/cancel_request","params":{"requestId":"1"}}\n')
            await settled()
            wrong = any(signal.aborted for signal, completion in active)
            rpc.data('{"jsonrpc":"2.0","method":"$/cancel_request","params":{"requestId":1}}\n')
            await settled()
            cancelled = [signal.aborted for signal, completion in active]
            if mode == 'duplicate':
                active[0][1].set_result('first completed')
                await settled()
            observations.append(dict(mode=mode, output=output, wrongTypeAborted=wrong, cancelled=cancelled))
            rpc.close()
            await rpc.drain()
            continue
        elif mode == 'eof':
            rpc.data('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
            await settled()
            rpc.end()
            await settled()
            observations.append(dict(mode=mode, output=output, aborted=active[0][0].aborted))
            await rpc.drain()
            continue
        elif mode in ('eof-parse', 'eof-request'):
            rpc.data('{' if mode == 'eof-parse' else '{"jsonrpc":"2.0","id":7,"method":"echo","params":"tail"}')
            rpc.end()
            await settled()
            observations.append(dict(mode=mode, output=output))
            await rpc.drain()
            continue
        else:
            messages = []
            rpc.receive = messages.append
            rpc.data('\n{"jsonrpc":"2.0","id":1,"method":"echo","params":"中文😀"}')
            rpc.end()
            await rpc.reader
            observations.append(dict(mode=mode, output=output, messages=messages))
            continue
        observations.append(dict(mode=mode, output=output))
        rpc.close()
        await rpc.drain()
    return observations


async def outgoing():
    observations = []
    for mode in ['result', 'remote-error', 'invalid', 'unknown', 'preabort', 'cancel', 'close', 'write-failure', 'mapper']:
        output = []
        def write(frame):
            output.append(json.loads(frame))
            if mode == 'write-failure':
                raise RuntimeError('write fixture failure')
        rpc = AcpRpc(write)
        controller = AbortController()
        if mode == 'preabort':
            controller.abort('fixture cancellation')
        def mapper(value):
            if mode == 'mapper':
                raise RuntimeError('mapper fixture failure')
            return {'mapped': value}
        pending = rpc.request('fixture/request', {'value': '中文'}, controller.signal, mapper)
        await settled()
        if mode == 'cancel':
            controller.abort('fixture cancellation')
            await settled()
        if mode == 'unknown':
            rpc.data('{"jsonrpc":"2.0","id":"0","result":"ignored"}\n')
            await settled()
        before = pending.done()
        if mode == 'close':
            rpc.end()
        elif mode != 'write-failure':
            packet = {'jsonrpc': '2.0', 'id': 0}
            if mode == 'remote-error':
                packet['error'] = {'code': -32602, 'message': 'fixture rejected', 'data': {'value': False}}
            elif mode == 'invalid':
                packet.update(result='ambiguous', error={'code': -32603, 'message': 'invalid'})
            else:
                packet['result'] = 'accepted'
            rpc.data(json.dumps(packet) + '\n')
        try:
            outcome = {'value': await pending}
        except Exception as error:
            outcome = {'error': {'message': str(error)}}
            if isinstance(error, RequestError):
                outcome['error']['code'] = error.code
                if error.data is not ABSENT:
                    outcome['error']['data'] = error.data
        await settled()
        observations.append(dict(mode=mode, output=output, settledBeforeReply=before, outcome=outcome, closed=rpc.closed))
        rpc.close()
        await rpc.drain()
    return observations


async def byte_frames():
    observations = []
    for case in cases['bytes']:
        output = []
        rpc = AcpRpc(lambda frame: output.append(json.loads(frame)))
        rpc.handlers['echo'] = lambda params, signal: None if params is ABSENT else params
        for byte in base64.b64decode(case['bytes']):
            rpc.data(bytes([byte]))
        for iteration in range(300):
            await asyncio.sleep(0)
        rpc.end()
        await rpc.reader
        await rpc.drain()
        observations.append({'mode': case['mode'], 'output': output})
    return observations

async def main():
    observations = []
    for section, observe in [('framing', framing), ('outgoing', outgoing), ('bytes', byte_frames)]:
        for row in await observe():
            row['mode'] = section + '/' + row['mode']
            observations.append(row)
    for case in cases['parameters'] + cases['fuzz']:
        mode = 'params/' + case['mode']
        try:
            observations.append({'mode': mode, 'value': validate_params(case['method'], case.get('params', ABSENT))})
        except RequestError as error:
            observations.append({'mode': mode, **error.result()})
    Path(sys.argv[2]).write_text(stringify_json(observations) + '\n', encoding='utf-8')

asyncio.run(main())
