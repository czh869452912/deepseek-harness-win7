"""Acquire exact licensed Office build inputs, never run on product startup."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dsh.office.runtime_inputs import MANIFESTS, verify_installed_runtime


def acquire(source, node, output, architecture):
    source, output = Path(source).absolute(), Path(output).absolute()
    records = json.loads((ROOT / 'scripts/office-runtime-inputs.json').read_text(encoding='utf-8'))['architectures']
    record = records[architecture]
    raw = (json.dumps(record['manifest'], indent=2) + '\n').encode('utf-8')
    if hashlib.sha256(raw).hexdigest() != MANIFESTS[architecture] or record['manifest_sha256'] != MANIFESTS[architecture]:
        raise ValueError('Office acquisition inventory differs.')
    output.mkdir(parents=True, exist_ok=False)
    destination = output / architecture
    destination.mkdir()
    archive = output / 'chromium.zip'
    browser = record['manifest']['browser']
    report = dict(command=[sys.executable] + sys.argv, architecture=architecture, source=browser['source'],
                  owner='Office runtime build-input preparation', purpose='Exact offline Portable/runtime input',
                  review_milestone='After Portable acceptance; retain only the verified shared runtime input and compact acquisition receipt.')
    start = time.monotonic()
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(browser['source'], timeout=30) as response, archive.open('xb') as stream:
            for data in iter(lambda: response.read(1024 * 1024), b''):
                stream.write(data)
                digest.update(data)
        if digest.hexdigest() != browser['archive_sha256']:
            raise ValueError('Chromium archive differs.')
        report.update(archive_bytes=archive.stat().st_size, archive_sha256=digest.hexdigest())
        package = source / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
        with zipfile.ZipFile(str(archive)) as zipped:
            for name, expected in record['manifest']['resources'].items():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if name.startswith('engine/'):
                    data = (package / name[len('engine/'):]).read_bytes()
                elif name.endswith('/CHROMIUM-LICENSE'):
                    with urllib.request.urlopen(browser['license_sources'][0], timeout=30) as response:
                        data = base64.b64decode(response.read(), validate=True)
                elif name.endswith('/CHROMIUM-THIRD-PARTY-LICENSES.txt'):
                    continue
                else:
                    data = zipped.read('chrome-win/' + name[len('browser/'):])
                if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise ValueError('Office acquisition resource differs: ' + name)
                target.write_bytes(data)
        command = [str(Path(node).absolute()), str(ROOT / 'scripts/native/office-browser/credits.mjs'), str(source), str(destination)]
        with (output / 'credits.log').open('wb') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=60, check=True)
        (destination / 'runtime.json').write_bytes(raw)
        verify_installed_runtime(destination, architecture)
        archive.unlink()
        report.update(status='passed', removed_download_bytes=report['archive_bytes'], retained_input=str(destination))
    except BaseException as cause:
        report.update(status='failed', error=repr(cause))
        # Retain raw diagnostics and partial input ownership; callers can retire
        # the identified payload after resolving its exact acquisition failure.
        raise
    finally:
        report['seconds'] = time.monotonic() - start
        (output / 'acquisition.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('source', 'node', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--architecture', choices=('x64', 'x86'), required=True)
    args = parser.parse_args()
    print(json.dumps(acquire(args.source, args.node, args.output, args.architecture)), flush=True)
