"""Exercise actual public SDK file converters against the Python browser owner."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh.office.browser_engine import BrowserOfficeEngine


async def main():
    parser = argparse.ArgumentParser()
    for key in ('source', 'node', 'browser', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.absolute()
    assert (root / '.goose/out').absolute() in out.parents
    out.mkdir()
    temporary = out / 'tmp'
    temporary.mkdir()
    source = args.source.absolute()
    options = dict(fontDirectories=[str(Path(os.environ['WINDIR']) / 'Fonts' / name) for name in ('arial.ttf', 'arialbd.ttf', 'cour.ttf', 'times.ttf')], fontMetadataCacheDirectory=False)
    fixture = source / 'packages/bundle/web-app/tests/fixtures/document-conversion.docx'
    operations = []
    for format in ('txt', 'pdf', 'docx', 'odt'):
        operations.append(dict(name='docx-' + format, kind='convert', request=dict(inputPath=str(fixture), outputPath=str(out / ('source-output.' + format)))))
    operations.append(dict(name='docx-images', kind='renderImages', request=dict(inputPath=str(fixture), outputDir=str(out / 'source-images'), dpi=96)))
    operations.append(dict(name='repeat-txt', kind='convert', request=dict(inputPath=str(fixture), outputPath=str(out / 'source-repeat.txt'))))
    request = out / 'source-request.json'
    request.write_text(json.dumps(dict(options=options, operations=operations, report=str(out / 'source-report.json'))), encoding='utf-8')
    command = [str(args.node.absolute()), str(root / 'scripts/oracles/rc022_office_converter.mjs'), str(source), str(request)]
    with (out / 'source.log').open('wb') as log:
        result = await asyncio.get_running_loop().run_in_executor(None, lambda: subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=120))
    assert result.returncode == 0
    expected = json.loads((out / 'source-report.json').read_text(encoding='utf-8'))['rows']
    package = source / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
    engine = BrowserOfficeEngine(str(args.browser.absolute()), str(package), temporary_directory=str(temporary))
    rows = []
    report = dict(command=[sys.executable] + sys.argv, rows=rows)
    def digest(path):
        data = Path(path).read_bytes()
        return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    try:
        converter = await engine.createConverter(options)
        for operation, original in zip(operations, expected):
            start = time.monotonic()
            request = dict(operation['request'])
            key = 'outputDir' if operation['kind'] == 'renderImages' else 'outputPath'
            request[key] = request[key].replace('source-', 'browser-')
            native = await getattr(converter, operation['kind'])(request)
            other = original['result']
            if key == 'outputDir':
                a, b = dict(native), dict(other)
                a['images'] = [dict(item, path=Path(item['path']).name, pixels=digest(item['path'])) for item in native['images']]
                b['images'] = [dict(item, path=Path(item['path']).name, pixels=digest(item['path'])) for item in other['images']]
                equal = a == b
            else:
                a, b = native, other
                equal = a == b
                if operation['name'] in ('docx-txt', 'repeat-txt'):
                    equal = equal and digest(request[key]) == digest(operation['request'][key])
            row = dict(name=operation['name'], equal=equal, browser=a, source=b, seconds=time.monotonic() - start,
                       cacheEntries=len(converter.state.cache), retainedRecords=len(converter.state.previous))
            rows.append(row)
            print(json.dumps(dict(name=row['name'], equal=equal, cacheEntries=row['cacheEntries'])), flush=True)
            assert equal, row
        report['status'] = 'passed'
    except BaseException as cause:
        report.update(status='failed', error=repr(cause))
        raise
    finally:
        await engine.close()
        report.update(activeTasks=len(engine.carrier.active), converters=len(engine.converters), remainingProfiles=[path.name for path in temporary.iterdir()])
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
