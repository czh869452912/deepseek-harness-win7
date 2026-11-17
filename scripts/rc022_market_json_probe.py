"""Exact pinned JSON syntax diagnostics, including UTF-16 and context boundaries."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
URL = 'https://market.example/index.json'


def cases():
    seeds = ['null', 'true', 'false', '0', '-1.25e+2', '"text"', '[]', '{}',
             '[0,true,null,"x"]', '{"a":[1,2],"b":{"c":false}}',
             '{"format":1,"title":"Market","plugins":[]}',
             '"\\u0000\\ud800\\udfff"', '"中文😀"', '\r\n[1,\r\n2]']
    rows = ['', ' ', '\r\n', 'undefined', 'NaN', 'Infinity', '[object Object]']
    replacements = ['{', '}', '[', ']', ',', ':', '"', '\\', '0', '-', '.',
                    '+', 'e', 't', 'f', 'n', 'x', ' ', '\t', '\r', '\n', '\0', '中', '😀']
    for seed in seeds:
        rows.append(seed)
        for at in range(len(seed) + 1):
            rows.extend([seed[:at], seed[:at] + seed[at + 1:]])
            for char in replacements:
                rows.extend([seed[:at] + char + seed[at:], seed[:at] + char + seed[at + 1:]])
    for prefix in ('', '[', '{"x":', '\r\n[\r', '\r\n[\n', '["😀",'):
        for value in ('-', '-x', '00', '1.', '1e', '1e-', 'tru', 'trueX', '"',
                      '"\\', '"\\中', '"\\😀', '"\\u', '"\\u0', '"\\u00', '"\\u000',
                      '"\\u000x', '"\\x"', '"\x1f"', '\ufeff', '\v'):
            rows.append(prefix + value)
    for length in (19, 20, 21, 22, 31, 41):
        for at in (0, 1, 9, 10, 11, length - 11, length - 10, length - 1):
            rows.append(' ' * at + 'x' + ' ' * (length - at - 1))
    return list(dict.fromkeys(rows))


async def observe():
    from dsh.boot.market_index_022 import observe_market_operations_async
    rows = []
    values = cases()
    for start in range(0, len(values), 512):
        rows.extend(await observe_market_operations_async([
            dict(kind='body', text=text.encode('utf-8').decode('utf-8-sig'), url=URL)
            for text in values[start:start + 512]]))
    if OUTPUT is not None:
        (OUTPUT/'native.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    return rows


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'texts.json'
    path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_json.mts', scope='Exact original parseIndexBody results: deterministic grammar mutations, truncation, escapes, numbers, nested containers, UTF-16/CRLF locations and 20/21-character context boundary. Resource exhaustion is outside this syntax corpus.',
        prepare=prepare, extra_inputs=[ROOT/'scripts/rc022_market_json_probe.py', ROOT/'dsh/boot/market_index_022.py', ROOT/'dsh/boot/market-index/manifest.json', ROOT/'scripts/native/market-index/json-diagnostics.ts', ROOT/'scripts/native/market-index/json-diagnostics-input.json'])
