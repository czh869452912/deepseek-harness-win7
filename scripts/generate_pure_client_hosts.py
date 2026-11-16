"""Capture only literal empty Host entrypoints; never infer from package names."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

TARGET = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'


def capture(source):
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    if revision != TARGET:
        raise RuntimeError('unexpected Source revision')
    rows = []
    for entry in sorted((source/'packages/client').glob('*/src/index.ts')):
        text = entry.read_text(encoding='utf-8')
        # A full match deliberately excludes imports, Config, declarations with
        # initializers and every other top-level executable statement.
        body = re.sub(r'/\*[\s\S]*?\*/|//[^\r\n]*', '', text)
        if not re.fullmatch(r'\s*export\s+function\s+apply\s*\(\s*\)\s*:\s*void\s*\{\s*\}\s*;?\s*', body):
            continue
        manifest = entry.parent.parent/'package.json'
        package = json.loads(manifest.read_text(encoding='utf-8'))
        if not package.get('dsh', {}).get('client'):
            raise RuntimeError('empty client entry lacks client declaration: '+str(entry))
        rows.append(dict(name=package['name'], source=entry.relative_to(source).as_posix(),
            source_sha256=hashlib.sha256(entry.read_bytes()).hexdigest(),
            manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest()))
    return dict(upstream=TARGET, rows=rows)


if __name__ == '__main__':
    Path(sys.argv[2]).write_text(json.dumps(capture(Path(sys.argv[1])), indent=2)+'\n', encoding='utf-8')
