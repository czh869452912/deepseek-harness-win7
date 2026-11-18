"""Compare current validators for the retained released-format logical corpus."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

CORPORA = [ROOT / 'scripts/oracles' / name for name in (
    'session_released_payload_cases.json', 'session_released_restore_cases.json')]


def cases():
    return [row for path in CORPORA for row in json.loads(path.read_text(encoding='utf-8'))]


async def native():
    from scripts.oracles.session_format_python import observe
    return json.loads(json.dumps([observe(row) for row in cases()]))


def prepare(output):
    path = output / 'cases.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_released_logical.mts',
        'Current pinned Source/native validation of retained released v0/v1 logical inputs; original historical expectations remain unchanged.',
        [Path(__file__).resolve(), *CORPORA,
         *sorted((ROOT / 'reference/packages/session/session-format-v0-to-v1/src').rglob('*.ts')),
         *sorted((ROOT / 'dsh/session/format_v0_to_v1').rglob('*.py'))], prepare=prepare)
