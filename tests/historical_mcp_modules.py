"""Sealed old MCP modules in an explicit compatibility unit composition.

Current helper packages are intentional here. This hybrid composition cannot
qualify either the current upstream or an historical release receipt.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from release_gate_fixtures import ROOT


def observe_module(name, output, environment):
    if name not in ('tools', 'supervisor'):
        raise ValueError('Unreviewed historical MCP module consumer')
    base = ROOT / 'tests/fixtures/mcp-historical-module-inputs'
    index = json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
    raw = gzip.decompress(base.with_suffix('.json.gz').read_bytes())
    assert index['source_commit'] == 'a4c74a91e06b00fe0b0937bde982170c526cc842'
    assert len(raw) == index['content_size'] == 42113
    assert hashlib.sha256(raw).hexdigest() == index['content_sha256'] == '2b87336a1373ad1fabec096dbb35a234c11ed06ac184b17bfaa62b39b25192c4'
    members = json.loads(raw)
    assert set(members) == set(index['members'])
    work = output.parent / 'sealed-mcp-module-model'
    work.mkdir()
    for path, text in members.items():
        content = text.encode('utf-8')
        row = index['members'][path]
        assert len(content) == row['size'] and hashlib.sha256(content).hexdigest() == row['sha256']
        assert hashlib.sha1(('blob ' + str(len(content)) + '\0').encode('ascii') + content).hexdigest() == row['git_blob']
        (work / path).write_bytes(content)
    spec = work / (name + '.probe.spec.ts')
    original = ROOT / 'scripts/oracles' / ('mcp_' + name + '.probe.spec.ts')
    spec.write_text(original.read_text(encoding='utf-8').replace(
        '../../reference/packages/mcp/mcp-client/src/', work.as_posix() + '/'), encoding='utf-8')
    config = work / 'vitest.config.mts'
    config.write_text(
        'import base from ' + json.dumps((ROOT / 'scripts/oracles/vitest.acp.config.mts').as_posix()) + '\n'
        'export default {...base,resolve:{...base.resolve,alias:[{find:"vitest",replacement:' +
        json.dumps((ROOT / 'scripts/oracles/official/node_modules/vitest/dist/index.js').as_posix()) +
        '},...base.resolve.alias]},test:{...base.test,include:[' + json.dumps(spec.as_posix()) + ']}}\n', encoding='utf-8')
    command = [shutil.which('node'), '--expose-internals',
               str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
               'run', '--config', str(config)]
    result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, **environment), capture_output=True, timeout=90)
    output.with_suffix('.module.log').write_bytes(result.stdout + result.stderr)
    output.with_suffix('.module-model.json').write_text(json.dumps(dict(
        command=command, exit_code=result.returncode, module_source=index,
        helper_target=json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream'],
        scope='Sealed old MCP modules with current helper dependencies; compatibility unit model only, not current Source or historical qualification'),
        indent=2), encoding='utf-8')
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    return json.loads(output.read_text(encoding='utf-8'))
