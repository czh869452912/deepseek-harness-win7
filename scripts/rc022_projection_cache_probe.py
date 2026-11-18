"""Actual current projection cache reads and prepared fallback over real JSON."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = None


def prepare(output):
    global WORKSPACE
    WORKSPACE = output / 'files'
    WORKSPACE.mkdir()
    pointer = output / 'workspace.txt'
    pointer.write_text(str(WORKSPACE), encoding='utf-8')
    return [pointer]


async def observe():
    from scripts.oracles.projection_cache_failure_python import observe as native_observer
    return await native_observer(WORKSPACE / 'native', 4)


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_projection_cache.mts',
        'Nine actual current-v4 JSON storage/domain/projection-cache consumers: malformed cold reads, prepared fallback, matching checkpoint, foreign lifecycle/cwd, row version, beyond-log and empty records, parser failure identity and stored bytes.',
        [Path(__file__).resolve(), ROOT / 'scripts/oracles/projection_cache_failure_python.py',
         ROOT / 'dsh/session/projection_cache_current.py', ROOT / 'dsh/session/projection_cache.py',
         ROOT / 'reference/packages/session/session-projection-cache/src/index.ts',
         ROOT / 'reference/packages/session/session-projection-cache/src/spec.ts'], prepare=prepare)
