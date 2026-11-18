"""Current Source and Python Unicode, cursor and semantic text consumers."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def run(command, stem):
    result = subprocess.run(command, cwd=str(ROOT), capture_output=True, timeout=120)
    (OUTPUT / (stem + '.log')).write_bytes(result.stdout + result.stderr)
    (OUTPUT / (stem + '.command.json')).write_text(json.dumps(dict(
        command=command, exit_code=result.returncode), indent=2), encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Native query text observer failed: ' + stem)


def prepare(output):
    global OUTPUT
    OUTPUT = output
    inputs = output / 'inputs.json'
    run([sys.executable, str(ROOT / 'scripts/oracles/session_text_inputs.py'),
         '--output', str(inputs)], 'inputs')
    return [inputs]


async def native():
    observed = {}
    for name in ('query_unicode', 'session_text'):
        path = OUTPUT / (name + '.json')
        command = [sys.executable, '-I', str(ROOT / 'scripts/oracles' / (name + '_python.py')),
                   str(path), '--root', str(ROOT), '--current-format']
        if name == 'session_text':
            command += ['--inputs', str(OUTPUT / 'inputs.json')]
        run(command, name)
        observed['unicode' if name == 'query_unicode' else 'text'] = json.loads(
            path.read_text(encoding='utf-8'))['observations']
    return observed


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_query_text.mts',
        'Actual current Source/Native: 1849 collation comparisons, 180 request fingerprints, five live SQLite cursor refusals, 7678 literal regex cases, 187 semantic event extraction boundaries and 18 current-v4 live/persisted/mixed corpus/lineage orders. Old Node22/ICU78 historical facts remain separately immutable; equality here is observed on the stated corpus, not arbitrary Unicode or locale equivalence.',
        [Path(__file__).resolve(), ROOT / 'scripts/oracles/session_text_inputs.py',
         ROOT / 'scripts/oracles/session_text_python.py', ROOT / 'scripts/oracles/query_unicode_python.py',
         ROOT / 'dsh/session/text_current.py', ROOT / 'dsh/session/query_current.py',
         ROOT / 'dsh/session/text.py', ROOT / 'dsh/session/session_query.py',
         ROOT / 'dsh/session/bin/unicode/CaseFolding-16.0.0.txt',
         ROOT / 'dsh/session/bin/unicode/unicode-current.json',
         ROOT / 'reference/packages/session-query/session-query/src/extraction.ts',
         ROOT / 'reference/packages/session-query/session-query/src/filters.ts',
         ROOT / 'reference/packages/session-query/session-query-sqlite/src/query.ts'], prepare=prepare)
