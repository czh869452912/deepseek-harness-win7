"""Fresh retained consumers, with immutable historical Source observations."""
import json
import subprocess
import sys

from evidence_fixtures import read_member
from release_gate_fixtures import ARCHIVE, ROOT


def tool_cache_pair(name, output):
    if name not in ('session-tools', 'projection-cache-failure', 'mcp-disposal'):
        raise ValueError('Unreviewed historical consumer: ' + name)
    source = read_member(ARCHIVE, 'full-gate-root.zip!/' + name + '-paired.source.json')
    native_path = output.with_suffix('.native.json')
    script = ROOT / 'scripts/oracles' / (name.replace('-', '_') + '_python.py')
    command = [sys.executable, '-I', str(script)]
    if name == 'projection-cache-failure':
        workspace = output.parent / 'owned-cache-files'
        workspace.mkdir()
        command.append(str(workspace))
    command += [str(native_path), '--root', str(ROOT)]
    completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, timeout=90)
    output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
    output.with_suffix('.command.json').write_text(json.dumps(dict(
        command=command, exit_code=completed.returncode, archive=ARCHIVE,
        source_member='full-gate-root.zip!/' + name + '-paired.source.json',
        scope='Historical compatibility consumer only; current Source executes separately'),
        indent=2), encoding='utf-8')
    if completed.returncode:
        raise RuntimeError('Historical Native consumer failed: ' + name + '\n' +
                           completed.stderr.decode('utf-8', errors='replace'))
    native = json.loads(native_path.read_text(encoding='utf-8'))
    if name == 'session-tools':
        from scripts import session_tools_oracle as oracle
        oracle.validate_runtime(native, ROOT, oracle.source_identity(source))
        assert source['rows'] == native['rows']
        count = 78
    elif name == 'projection-cache-failure':
        from scripts import projection_cache_failure_oracle as oracle
        oracle.validate_observations(source)
        oracle.validate_runtime(native)
        assert source == native['observations']
        count = 9
    else:
        from scripts import mcp_disposal_oracle as oracle
        source = dict(supervisor=source, factory=read_member(ARCHIVE,
            'full-gate-root.zip!/mcp-disposal-paired.factory.json'))
        oracle.validate_observations(source)
        oracle.validate_runtime(native)
        assert source == {key: native[key] for key in source}
        count = 7
    report = dict(status='passed', cases=count, scope='Historical compatibility unit checks only')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report, source, native
