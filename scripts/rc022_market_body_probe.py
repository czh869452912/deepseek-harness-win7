"""Strict UTF-8/JSON behavior, preserving separate engine diagnostic evidence."""
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
FILES = None
URL = 'https://market.example/index.json'


def cases():
    valid = b'{"format":1,"title":"Market","plugins":[]}'
    rows = [valid, b'\xef\xbb\xbf'+valid, b'\xef\xbb\xbf\xef\xbb\xbf'+valid,
        b'', b'{', b'null', b'[]', b'true', b'2', b'"text"', b'\x00', b'\xff\xfe',
        b'\x80', b'\xc0\x80', b'\xc1\xbf', b'\xc2', b'\xe0\x80\x80', b'\xe0\xa0',
        b'\xed\xa0\x80', b'\xef\xbf', b'\xf0\x80\x80\x80', b'\xf0\x90\x80',
        b'\xf4\x90\x80\x80', b'\xf5\x80\x80\x80', b'\xfe', b'\xff', valid+b'\xff',
        b'{"format":1,}', b'{/*comment*/}', b'{"format":NaN}', b'{"format":Infinity}',
        b'{"format":01}', b'{"format":1e309,"title":"x","plugins":[]}',
        b'{"format":1,"title":"x","plugins":[],"format":2}',
        b'{"format":2,"title":"x","plugins":[],"format":1}',
        b'{"format":1,"title":"\\ud800","plugins":[]}',
        b'{"format":1,"title":"\\u0000","plugins":[]}',
        '{"format":1,"title":"\u0080\u0800\ud7ff\ue000\uffff\U00010000\U0010ffff","plugins":[]}'.encode('utf-8'),
        b' \t\r\n'+valid+b' \t\r\n', b'{"format":1,"title":"x\nx","plugins":[]}',
        b'{"format":1,"title":"x","plugins":[]} trailing']
    return rows


async def observe():
    from dsh.boot.market_index_022 import parse_index_body
    raw = [await parse_index_body(body, URL) for body in cases()]
    if FILES is not None:
        (FILES/'native-diagnostics.json').write_text(json.dumps(raw, ensure_ascii=True), encoding='utf-8')
    return summarize(raw)


def summarize(raw):
    rows = []
    for result in raw:
        if not result['ok'] and result['reason'].startswith('must be JSON: '):
            rows.append(dict(ok=False, path=result['path'], reasonPrefix='must be JSON: ', diagnosticPresent=len(result['reason'])>14))
        else: rows.append(result)
    return rows


def prepare(output):
    global FILES
    FILES = output
    path = output/'bodies.json'
    path.write_text(json.dumps([base64.b64encode(body).decode('ascii') for body in cases()]), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_body.mts', scope='Strict UTF-8 including overlong/surrogate/out-of-range/truncated sequences, BOM, JS JSON acceptance and pinned format validation. Invalid JSON compares path/prefix/present diagnostic only; original V8 and QuickJS prose retained separately and not claimed identical.',
        prepare=prepare, extra_inputs=[ROOT/'dsh/boot/market_index_022.py', ROOT/'dsh/boot/market-index/manifest.json', ROOT/'scripts/rc022_market_body_probe.py'])
