"""Pair original SDK disk-cache workers and the owned browser scan, including interop."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh.core.abort import AbortController
from dsh.cordis.json_text import stringify_json
from dsh.office.browser_engine import BrowserOfficeEngine, _State
from dsh.office.contracts import resolve_request


async def main():
    parser = argparse.ArgumentParser()
    for name in ('source', 'node', 'browser', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.absolute()
    assert (root / '.goose/out').absolute() in out.parents
    out.mkdir()
    temporary = out / 'tmp'
    temporary.mkdir()
    source = args.source.absolute()
    assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    package = source / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
    options = dict(fontDirectories=[str(Path(os.environ['WINDIR']) / 'Fonts' / name)
                                   for name in ('arial.ttf', 'arialbd.ttf', 'cour.ttf', 'times.ttf')])
    engine = BrowserOfficeEngine(str(args.browser.absolute()), str(package), temporary_directory=str(temporary))
    rows = []
    report = dict(command=[sys.executable] + sys.argv, rows=rows)
    def normalize(value):
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items() if key != 'generation'}
        if isinstance(value, str) and value.startswith('/physical/'):
            return value[len('/physical/'):]
        return value
    seed = None
    try:
        bootstrap = await engine.createConverter(dict(options, fontMetadataCacheDirectory=False))
        for name in ('cold', 'warm-source-cache', 'warm-reused-metadata', 'bad-digest', 'extra-field', 'truncated', 'oversized', 'disabled'):
            run = out / name
            run.mkdir()
            original_directory, native_directory = run / 'source-cache', run / 'browser-cache'
            original_directory.mkdir()
            native_directory.mkdir()
            payload = seed
            if name == 'warm-reused-metadata':
                value = json.loads(seed)
                for record in value['records']:
                    for face in record['faces']:
                        face['family'] = 'Observed cached metadata'
                value['digest'] = hashlib.sha256(stringify_json(value['records']).encode('utf-8')).hexdigest()
                payload = stringify_json(value).encode('utf-8')
            elif name == 'bad-digest':
                value = json.loads(seed)
                value['digest'] = '0' * 64
                payload = json.dumps(value).encode('utf-8')
            elif name == 'extra-field':
                value = json.loads(seed)
                value['unexpected'] = True
                payload = json.dumps(value).encode('utf-8')
            elif name == 'truncated':
                payload = seed[:len(seed) // 2]
            if payload is not None and name != 'disabled':
                for directory in (original_directory, native_directory):
                    (directory / 'font-metadata.json').write_bytes(payload)
            maximum = 32 if name == 'oversized' else 33554432
            selected = dict(options, fontMetadataCacheDirectory=False if name == 'disabled' else str(original_directory),
                            maxFontMetadataCacheBytes=maximum)
            request = run / 'request.json'
            request.write_text(json.dumps(dict(metadata=True, scanOnly=True, options=selected, fontPaths=options['fontDirectories'])), encoding='utf-8')
            command = [str(args.node.absolute()), str(root / 'scripts/oracles/rc022_office_sdk.mjs'),
                       str(source), str(request), str(run / 'source')]
            with (run / 'source.log').open('wb') as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=60)
            assert completed.returncode == 0, name
            expected = json.loads((run / 'source/report.json').read_text(encoding='utf-8'))['snapshot']
            assert expected['ok'], expected
            selected['fontMetadataCacheDirectory'] = False if name == 'disabled' else str(native_directory)
            state = _State(engine, resolve_request('options', selected))
            volume, host, actual = await state.acquire(AbortController().signal)
            volume.validate(actual['records'])
            left = native_directory / 'font-metadata.json'
            right = original_directory / 'font-metadata.json'
            same = normalize(actual) == normalize(expected['snapshot'])
            cache_equal = left.exists() == right.exists() and (not left.exists() or left.read_bytes() == right.read_bytes())
            row = dict(name=name, snapshots_equal=same, cache_bytes_equal=cache_equal,
                       cache_bytes=left.stat().st_size if left.exists() else None,
                       native_records=len(actual['records']), leftovers=[p.name for p in native_directory.glob('*.tmp')])
            rows.append(row)
            print(json.dumps(row), flush=True)
            assert same and cache_equal and not row['leftovers'], name
            if name == 'warm-reused-metadata':
                assert {face['family'] for face in actual['faces']} == {'Observed cached metadata'}
            if name == 'cold':
                seed = left.read_bytes()
        # The browser's physical-path cache was consumed by original Workers
        # in subsequent cases, and its exact bytes match original encoding.
        await bootstrap.dispose()
        report['status'] = 'passed'
    except BaseException as cause:
        report.update(status='failed', error=repr(cause))
        raise
    finally:
        await engine.close()
        report.update(activeTasks=len(engine.carrier.active), remainingProfiles=[p.name for p in temporary.iterdir()])
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
