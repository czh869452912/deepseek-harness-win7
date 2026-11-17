"""Run the controlled pinned WASM Office probe with only Python and Chromium."""
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
from dsh.office.browser_carrier import BrowserCarrier


async def main():
    parser = argparse.ArgumentParser()
    for key in ('source', 'browser', 'output'):
        parser.add_argument('--' + key, required=True, type=Path)
    parser.add_argument('--font', type=Path, default=Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/arial.ttf')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if (root / '.goose/out').resolve() not in out.parents:
        raise ValueError('Output must be a fresh owned .goose/out child.')
    source = args.source.resolve()
    upstream = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != upstream or subprocess.check_output(
            ['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise ValueError('Source must be the clean pinned checkout.')
    out.mkdir()
    temporary = out / 'tmp'
    temporary.mkdir()
    package = source / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
    assets = {name: package / 'assets' / name for name in
              ('dsoffice.cjs', 'dsoffice.wasm', 'dsoffice.data', 'dsoffice.data.js.metadata')}
    manifest = json.loads((package / 'prebuilds.json').read_text(encoding='utf-8'))
    assets['font.ttf'] = args.font.resolve()
    assets['input.docx'] = source / 'packages/bundle/web-app/tests/fixtures/document-conversion.docx'
    identities = {}
    for name, file in assets.items():
        data = file.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        identities[name] = dict(size=len(data), sha256=digest)
        if name.startswith('dsoffice.') and manifest['files']['assets/' + name] != digest:
            raise ValueError('Pinned engine asset mismatch: ' + name)
    probe = (root / 'scripts/rc022_office_wasm_probe.mjs').read_text(encoding='utf-8')
    worker = probe[probe.index('async function workerMain(base)'):probe.index('\ntry{\n browser=')]
    worker = worker.replace('trace.push(', 'observe(').replace('const trace=[],fonts=[];', "const trace=[],fonts=[];const observe=(...items)=>{fetch(base+'/trace?'+encodeURIComponent(JSON.stringify(items)));return trace.push(...items);};")
    worker += "\nworkerMain(new URL('.',location.href).href.slice(0,-1));"
    carrier = BrowserCarrier(str(args.browser.resolve()), temporary_directory=str(temporary))
    report = dict(upstream=upstream, command=[sys.executable] + sys.argv, inputs=identities,
                  scope='Actual pinned WASM conversion over Python 3.8 stdlib HTTP carrier. Controlled Arial font; no font matching or Windows 7 execution qualification.')
    start = time.monotonic()
    observations = []
    try:
        result = await carrier.run(worker, assets, timeout=90, observe_request=lambda method,name: observations.append(dict(method=method,path=name,seconds=time.monotonic()-start)))
        files = result.pop('files', {})
        report['result'] = result
        report['outputs'] = {}
        for format, data in files.items():
            (out / ('actual.' + format)).write_bytes(data)
            report['outputs'][format] = dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        if not result['okay']:
            raise RuntimeError(result.get('error', 'Office conversion failed.'))
        assert b'Office preview ready' in files['txt']
        assert files['pdf'].startswith(b'%PDF-') and files['png'].startswith(b'\x89PNG\r\n\x1a\n')
        assert result['trace'][-3:] == ['document-destroyed', 'office-destroyed', 'pthreads-terminated']
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        await carrier.close()
        report.update(seconds=time.monotonic() - start, requests=observations, activeTasks=len(carrier.active), remainingProfiles=[p.name for p in temporary.iterdir()])
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key not in ('inputs', 'result', 'command', 'requests')}))


if __name__ == '__main__':
    asyncio.run(main())
