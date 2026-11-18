"""Fresh sealed old worker composition for retained compatibility tests.

This deliberately uses the old Node22 worker and its explicit fixture helpers.
It cannot qualify current Source or the original archived release candidate.
"""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from release_gate_fixtures import ROOT


def observe_session(output):
    base = ROOT / 'tests/fixtures/workflow-historical-module-inputs'
    index = json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
    raw = gzip.decompress(base.with_suffix('.json.gz').read_bytes())
    assert len(raw) == index['content_size'] == 295824
    assert hashlib.sha256(raw).hexdigest() == index['content_sha256'] == '4ca5594cf37827e137e90167a2ef579897db440fc35b2e9e02afdb71354675d0'
    assert index['source_commit'] == 'a4c74a91e06b00fe0b0937bde982170c526cc842'
    members = json.loads(raw)
    assert set(members) == set(index['members'])
    work = output.parent / 'sealed-old-worker'; work.mkdir()
    for name, text in members.items():
        path = Path(name)
        assert not path.is_absolute() and '..' not in path.parts
        content = text.encode('utf-8'); row = index['members'][name]
        assert len(content) == row['size'] and hashlib.sha256(content).hexdigest() == row['sha256']
        assert hashlib.sha1(('blob ' + str(len(content)) + '\0').encode('ascii') + content).hexdigest() == row['git_blob']
        target = work / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    fixture = work / 'tests/fixtures/javascript-workflow/cases.json'
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes((ROOT / 'tests/fixtures/javascript-workflow/cases.json').read_bytes())
    observer = (ROOT / 'scripts/oracles/javascript_workflow_source.mjs').read_text(encoding='utf-8')
    # Pin checking is replaced only in this copied observer: the materialized
    # old closure above has already been checked byte-for-byte and by Git blob.
    start = observer.index("if (execFileSync('git'")
    end = observer.index('const output =', start)
    observer = observer[:start] + observer[end:]
    observer = observer.replace("'./node_modules/esbuild/lib/main.js'",
        json.dumps((ROOT / 'scripts/oracles/node_modules/esbuild/lib/main.js').as_uri()))
    script = work / 'observe.mjs'; script.write_text(observer, encoding='utf-8')
    node = ROOT / '.goose/tools/node-22.22.2/node.exe'
    command = [str(node), str(script), str(output)]
    result = subprocess.run(command, cwd=str(work), capture_output=True, timeout=120)
    (output.parent / 'source.log').write_bytes(result.stdout + result.stderr)
    (output.parent / 'compatibility-composition.json').write_text(json.dumps(dict(
        command=command, exit_code=result.returncode, inputs=index,
        scope='Fresh old worker composition against retained Native; never current Source/release acceptance'), indent=2), encoding='utf-8')
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    return json.loads((output / 'source.json').read_text(encoding='utf-8'))
