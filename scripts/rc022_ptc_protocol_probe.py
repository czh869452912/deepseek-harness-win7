"""Pair bounded control framing and actual outstanding-binding limits."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = ROOT


def cases():
    def frame(text):
        return json.dumps(dict(t='q', m='ping', a=[text]), ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
    exact = frame('x'*(65-len(frame(''))))
    assert len(exact) == 65
    result = [dict(name='fragmented', chunks=[list(bytes([n])) for n in frame('你好🙂\ninside')], maximum=128),
        dict(name='consecutive', chunks=[list(frame('a')+frame('b'))], maximum=64),
        dict(name='exact', chunks=[list(exact)], maximum=64),
        dict(name='crlf', chunks=[list(frame('a')[:-1]+b'\r\n')], maximum=64),
        dict(name='replacement', chunks=[list(frame('a').replace(b'["a"]', b'["\xff"]'))], maximum=64)]
    for name, value, eof in [('overflow', exact[:-1]+b'x', False), ('bad-json', b'{\n', False),
            ('non-object', b'null\n', False), ('array', b'[]\n', False),
            ('space-prefix', b' {}\n', False), ('empty-line', b'\n', False),
            ('incomplete', b'{', True), ('empty-eof', b'', True),
            ('length-prefix', bytes([0,0,0,2,123,125]), False),
            ('bad-first-then-valid', b'{\n'+frame('not-called'), False),
            ('non-json-number', b'{"t":"q","m":"ping","a":[NaN]}\n', False)]:
        result.append(dict(name=name, chunks=[list(value)], maximum=64, eof=eof))
    return result


async def observe():
    from dsh.code_runtime.protocol import JsonLines, QueuedBytes, ProtocolError, ControlClosedError
    from dsh.cordis import Context
    from dsh.code_runtime.ptc import PythonPtcRuntime
    rows = []
    for case in cases():
        decoder = JsonLines(case['maximum'])
        values = []
        row = dict(name=case['name'], values=values, failure=None)
        try:
            for chunk in case['chunks']:
                decoder.feed(bytes(chunk), lambda value, size: values.append(value['a'][0]))
            if case.get('eof'):
                decoder.end()
        except ProtocolError:
            row['failure'] = 'protocol'
        except ControlClosedError:
            row['failure'] = 'closed'
        rows.append(row)
    for maximum, count in ((256, 1), (256, 4), (97, 1), (96, 1)):
        queue = QueuedBytes(maximum)
        admitted = 0
        failed = False
        for unused in range(count):
            try:
                queue.admit(dict(m='notice', a=['x'*64], t='q'))
                admitted += 1
            except ProtocolError:
                failed = True
                break
        rows.append(dict(name='outgoing', maximum=maximum, count=count, admitted=admitted, failure='protocol' if failed else None))
    for config in (dict(maxPendingCalls=1), dict(maxMessageBytes=512)):
        ctx = Context()
        await ctx.plugin(PythonPtcRuntime, dict(timeoutMs=5000, **config))
        runtime = ctx.get('ptcRuntime')
        release = asyncio.Event()
        settled = asyncio.Event()
        calls = []
        async def slow(args):
            calls.append(args)
            await release.wait()
            settled.set()
            return None
        try:
            result = await runtime.run(runtime.resolve(dict(
                program="import asyncio\nfirst=asyncio.create_task(tools.slow('x'*300))\nawait asyncio.sleep(.05)\nawait asyncio.gather(first, tools.slow('y'*300))",
                bindings=[dict({'global':'tools'}, functions=dict(slow=slow))], cwd=str(WORKSPACE))))
            rows.append(dict(name='pending', config=config, error=result.get('error', {}).get('kind'),
                             calls=len(calls), callerOwned=not settled.is_set()))
        finally:
            release.set()
            if calls:
                await settled.wait()
            await ctx.fiber.dispose()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE = output.parent/'tmp'/'workspace'
    WORKSPACE.mkdir()
    path = output/'cases.json'
    path.write_text(json.dumps(dict(cases=cases(), workspace=str(WORKSPACE))), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_protocol.mts',
        'Bounded control JSON lines, byte-fragmented UTF-8, malformed/foreign frames and EOF, native writable queue, actual process pending binding count/bytes and late caller ownership. Python transport remains a Python-specific bootstrap, not the Node/birpc ABI.',
        [Path(__file__).resolve(), ROOT/'dsh/code_runtime/protocol.py', ROOT/'dsh/code_runtime/process.py', ROOT/'dsh/code_runtime/ptc.py'], prepare)
