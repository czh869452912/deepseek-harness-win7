"""Pair actual original Office-font discovery against the physical browser volume."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh.office.browser_carrier import BrowserCarrier
from dsh.office.font_discovery import host_font_volume


async def main():
    parser = argparse.ArgumentParser()
    for key in ('source', 'node', 'browser', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    assert (root / '.goose/out').resolve() in out.parents
    target = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    assert subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip() == target
    assert not subprocess.check_output(['git', '-C', str(args.source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    out.mkdir()
    temporary, fixtures = out / 'tmp', out / 'fixtures'
    temporary.mkdir()
    fixtures.mkdir()
    env = {key: str(fixtures / value) for key, value in [('SystemRoot', 'Windows'), ('LOCALAPPDATA', 'Local'), ('ProgramFiles', 'Programs'), ('ProgramFiles(x86)', 'Programs32')]}
    bundled = Path(env['ProgramFiles']) / 'Microsoft Office/root/vfs/Fonts/private'
    bundled32 = Path(env['ProgramFiles(x86)']) / 'Microsoft Office/root/vfs/Fonts/private'
    cloud = Path(env['LOCALAPPDATA']) / 'Microsoft/FontCache'
    primary = Path(env['SystemRoot']) / 'Fonts'
    fontroot = Path(os.environ['WINDIR']) / 'Fonts'
    inputs = []
    for path, name in [(primary / 'arial.ttf', 'arial.ttf'), (bundled / 'times.ttf', 'times.ttf'),
                       (bundled / 'arialbd.ttf', 'arialbd.ttf'), (bundled / 'ignored.ttf', 'cour.ttf'),
                       (bundled / 'nested/arial.ttf', 'cour.ttf'), (bundled32 / 'cour.ttf', 'cour.ttf'),
                       (cloud / 'version2/common.ttf', 'arialbd.ttf'), (cloud / 'version10/common.ttf', 'cour.ttf'),
                       (cloud / 'version30/PreviewFont/hidden.ttf', 'times.ttf')]:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(fontroot / name), str(path))
        inputs.append(dict(path=str(path.relative_to(out)), bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    runtime = root / 'dsh/office/browser_runtime'
    manifest = json.loads((runtime / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['resources'].items():
        assert hashlib.sha256((runtime / name).read_bytes()).hexdigest() == expected
    carrier = BrowserCarrier(str(args.browser), temporary_directory=str(temporary))
    rows = []
    report = dict(target_upstream=target, command=[sys.executable] + sys.argv, fixture_inputs=inputs,
                  runtime_manifest_sha256=hashlib.sha256((runtime / 'manifest.json').read_bytes()).hexdigest(), rows=rows)
    try:
        for name, options in [('default-roots', {}), ('remaining-one', dict(maxFontFiles=2)),
                              ('no-remaining', dict(maxFontFiles=1)), ('explicit-empty', dict(fontDirectories=[])),
                              ('explicit-primary', dict(fontDirectories=[str(primary)]))]:
            start = time.monotonic()
            run = out / name
            run.mkdir()
            volume, host = host_font_volume(options, home=str(fixtures / 'home'), env=env)
            selected = dict(options, fontDirectories=volume.paths, includeOfficeFonts='fontDirectories' not in options, fontMetadataCacheDirectory=False)
            request = dict(options=selected, volume=volume.manifest(), host=host, scanOnly=True,
                           engine=dict(backend='wasm', loader='unused.cjs', data='unused.data', wasm='unused.wasm', metadata='unused.metadata'),
                           fontPaths=[asset.path for asset in volume.assets.values() if '/physical/' + asset.path in volume.paths])
            request_path = run / 'request.json'
            request_path.write_text(json.dumps(request), encoding='utf-8')
            command = [str(args.node), str(root / 'scripts/oracles/rc022_office_sdk.mjs'), str(args.source), str(request_path), str(run / 'source')]
            with (run / 'source.log').open('wb') as log:
                result = await asyncio.get_running_loop().run_in_executor(None, lambda: subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=60))
            assert result.returncode == 0
            browser = await carrier.run("importScripts('sdk.js')", dict(volume.assets, **{'sdk.js': runtime / 'worker.js', 'request.json': request_path}), timeout=60)
            expected = json.loads((run / 'source/report.json').read_text(encoding='utf-8'))['snapshot']
            assert browser['ok'] and expected['ok'], (browser, expected)
            volume.validate(browser['snapshot']['records'])
            def normalize(value):
                if isinstance(value, list):
                    return [normalize(item) for item in value]
                if isinstance(value, dict):
                    return {key: normalize(item) for key, item in value.items() if key != 'generation'}
                if isinstance(value, str) and os.path.isabs(value) and not value.startswith('/physical/'):
                    return '/physical/' + os.path.realpath(value)
                return value
            native, original = normalize(browser['snapshot']), normalize(expected['snapshot'])
            row = dict(name=name, equal=native == original, browser=native, source=original,
                       adapter=browser['adapter'], seconds=time.monotonic() - start)
            rows.append(row)
            (run / 'comparison.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
            print(json.dumps(dict(name=name, equal=row['equal'], families=[face['family'] for face in native['faces']])), flush=True)
            assert row['equal'], name
            assert browser['adapter'] == dict(openDescriptors=0, retainedReadBuffers=0)
        report['status'] = 'passed'
    except BaseException as cause:
        report.update(status='failed', error=repr(cause))
        raise
    finally:
        await carrier.close()
        report.update(activeTasks=len(carrier.active), remainingProfiles=[entry.name for entry in temporary.iterdir()])
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
