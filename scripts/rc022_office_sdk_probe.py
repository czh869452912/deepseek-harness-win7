"""Pair actual original Node/WASM SDK workers against the browser-volume build."""
import argparse
import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh.office.browser_carrier import BrowserCarrier
from dsh.office.font_volume import FontVolume


def digest(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


async def main():
    parser = argparse.ArgumentParser()
    for key in ('source', 'node', 'browser', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve()
    out = args.output.resolve()
    if (root / '.goose/out').resolve() not in out.parents:
        raise ValueError('Output must be a fresh owned .goose/out child.')
    target = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != target or subprocess.check_output(
            ['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise ValueError('Source must be the clean pinned checkout.')
    out.mkdir()
    temporary = out / 'tmp'
    temporary.mkdir()
    runtime = root / 'dsh/office/browser_runtime'
    manifest = json.loads((runtime / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['target_upstream'] == target
    for name, expected in manifest['resources'].items():
        assert hashlib.sha256((runtime / name).read_bytes()).hexdigest() == expected, name
    package = source / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
    engine_manifest = json.loads((package / 'prebuilds.json').read_text(encoding='utf-8'))
    assets = {name: package / 'assets' / name for name in ('dsoffice.cjs', 'dsoffice.wasm', 'dsoffice.data', 'dsoffice.data.js.metadata')}
    for name, file in assets.items():
        assert hashlib.sha256(file.read_bytes()).hexdigest() == engine_manifest['files']['assets/' + name]
    assets['sdk.js'] = runtime / 'worker.js'
    physical = []
    for name in sorted(['arial.ttf', 'arialbd.ttf', 'times.ttf', 'cour.ttf']):
        path = Path(os.environ['WINDIR']) / 'Fonts' / name
        physical.append(str(path))
    volume = FontVolume(physical)
    empty_volume = FontVolume([])
    assets.update(volume.assets)
    fixture = source / 'packages/bundle/web-app/tests/fixtures/document-conversion.docx'
    original = fixture.read_bytes()
    def changed_font(name):
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as archive, zipfile.ZipFile(output, 'w') as changed:
            for entry in archive.infolist():
                changed.writestr(entry, archive.read(entry).replace(b'Liberation Sans', name.encode('utf-8')))
        return output.getvalue()
    cases = [dict(name='scan-original', scanOnly=True)]
    for format in ('txt', 'pdf', 'docx', 'odt'):
        cases.append(dict(name='docx-' + format, operation=dict(format=format, recalculate=False)))
    cases += [dict(name='present-font', input=changed_font('Arial'), operation=dict(format='txt', recalculate=False)),
              dict(name='missing-font', input=changed_font('DSH Missing Font 2026'), operation=dict(format='txt', recalculate=False)),
              dict(name='docx-images', operation=dict(kind='images', inputPath='/input.docx', outputDir='/output', dpi=96, maxPages=10, maxPixels=16777216, maxDimension=4096)),
              dict(name='pdf-images', extension='pdf', operation=dict(kind='images', inputPath='/input.pdf', outputDir='/output', dpi=96, maxPages=10, maxPixels=16777216, maxDimension=4096)),
              dict(name='invalid-document', input=b'not an office archive', operation=dict(format='pdf', recalculate=False)),
              dict(name='output-limit', options=dict(maxOutputBytes=10), operation=dict(format='pdf', recalculate=False)),
              dict(name='loaded-font-limit', options=dict(maxLoadedFontBytes=1), operation=dict(format='txt', recalculate=False)),
              dict(name='archive-entry-limit', options=dict(maxArchiveEntries=1), operation=dict(format='pdf', recalculate=False)),
              dict(name='scan-file-limit', scanOnly=True, options=dict(maxFontFiles=1)),
              dict(name='scan-font-byte-limit', scanOnly=True, options=dict(maxFontFileBytes=1)),
              dict(name='no-fonts', noFonts=True, operation=dict(format='txt', recalculate=False))]
    rows = []
    report = dict(command=[sys.executable] + sys.argv, target_upstream=target, runtime_manifest=digest((runtime / 'manifest.json').read_bytes()), rows=rows,
                  comparison_scope='Actual identity-checked physical font assets and unchanged SDK scan/match/export/raster bodies. Original path characters follow a constant private prefix. Snapshot sources validate before publishing. Explicit roots, not default discovery or disk-cache qualification.')
    carrier = BrowserCarrier(str(args.browser.resolve()), temporary_directory=str(temporary))
    def normalize(value):
        if isinstance(value, bytes):
            return digest(value)
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items() if key not in ('stack', 'snapshot', 'fontCache', 'files', 'adapter', 'metadata')}
        if isinstance(value, str):
            if value in physical:
                return '/physical/' + os.path.realpath(value)
            return value
        return value
    try:
        for case in cases:
            start = time.monotonic()
            run = out / case['name']
            run.mkdir()
            extension = case.get('extension', 'docx')
            data = case.get('input', original)
            if extension == 'pdf':
                data = (out / 'docx-pdf/browser-output.pdf').read_bytes()
            input_path = run / ('input.' + extension)
            input_path.write_bytes(data)
            selected_volume = empty_volume if case.get('noFonts') else volume
            options = dict(fontDirectories=selected_volume.paths, includeOfficeFonts=False, fontMetadataCacheDirectory=False, **case.get('options', {}))
            request = dict(engine=dict(backend='wasm', loader='dsoffice.cjs', data='dsoffice.data', wasm='dsoffice.wasm', metadata='dsoffice.data.js.metadata', programDirectory='/instdir/program'),
                           options=options, volume=selected_volume.manifest(),
                           scanOnly=case.get('scanOnly', False), extension=extension, inputRoute='input.' + extension,
                           operation=case.get('operation', dict(format='pdf', recalculate=False)), inputPath=str(input_path), fontPaths=[] if case.get('noFonts') else physical)
            request_path = run / 'request.json'
            request_path.write_text(json.dumps(request), encoding='utf-8')
            command = [str(args.node.resolve()), str(root / 'scripts/oracles/rc022_office_sdk.mjs'), str(source), str(request_path), str(run / 'source')]
            with (run / 'source.log').open('wb') as log:
                result = await asyncio.get_running_loop().run_in_executor(None, lambda: subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=75))
            assert result.returncode == 0, case['name'] + ': original worker failed'
            local_assets = dict(assets, **{'request.json': request_path, 'input.' + extension: input_path})
            browser = await carrier.run("importScripts('sdk.js')", local_assets, timeout=60)
            assert browser['adapter'] == dict(openDescriptors=0, retainedReadBuffers=0)
            if 'snapshot' in browser:
                selected_volume.validate(browser['snapshot']['records'])
            raw_source = json.loads((run / 'source/report.json').read_text(encoding='utf-8'))
            native = normalize(browser)
            expected = normalize(raw_source.get('result', raw_source['snapshot']))
            # Scan identity/generation contain physical carrier paths and stat representations.
            if case.get('scanOnly') and browser.get('ok'):
                keys = ('path', 'dev', 'ino', 'size', 'mtimeMs', 'ctimeMs', 'faceIndex', 'family', 'style', 'aliases', 'weight', 'width', 'fixed', 'italic', 'postscriptName')
                native['faces'] = [{key: normalize(face[key]) for key in keys} for face in browser['snapshot']['faces']]
                expected['faces'] = [{key: normalize(face[key]) for key in keys} for face in raw_source['snapshot']['snapshot']['faces']]
            if 'output' in browser:
                format = request['operation']['format']
                (run / ('browser-output.' + format)).write_bytes(browser['output'])
                if format in ('pdf', 'docx', 'odt'):
                    # Export containers include dates. Keep complete actual bytes; compare signature,
                    # actual raster separately and the stable structured result here.
                    expected.pop('output', None)
                    native.pop('output', None)
            if 'images' in browser:
                for item in browser['images']['images']:
                    path = item['path']
                    pixels = browser['files'][path]
                    (run / ('browser-' + Path(path).name)).write_bytes(pixels)
                for result_value, side in ((native, 'browser'), (expected, 'source')):
                    for item in result_value['images']['images']:
                        path = item['path']
                        item['pixels'] = digest(browser['files'][path] if side == 'browser' else Path(path).read_bytes())
                        item['path'] = Path(path).name
                    result_value['images']['inputPath'] = '/input.' + extension
            row = dict(name=case['name'], input=digest(data), equal=native == expected, browser=native, source=expected, adapter=browser['adapter'], seconds=time.monotonic() - start)
            rows.append(row)
            (run / 'comparison.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
            print(json.dumps(dict(case=case['name'], equal=row['equal'], seconds=row['seconds'])), flush=True)
            if not row['equal']:
                raise AssertionError('Original/browser SDK mismatch: ' + case['name'])
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        await carrier.close()
        report.update(activeTasks=len(carrier.active), remainingProfiles=[path.name for path in temporary.iterdir()])
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
