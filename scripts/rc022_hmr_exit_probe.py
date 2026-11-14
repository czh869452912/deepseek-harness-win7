"""Observe application disposal immediately after a self-replaced provider runs."""
import asyncio
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
from scripts import rc022_hmr_watch_probe as watch
OUTPUT = None


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text('{"settleBeforeExit":false}', encoding='utf-8')
    return [path]


async def native():
    return await asyncio.wait_for(watch.observe(OUTPUT/'files/native', settle_before_exit=False), 20)


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_hmr_watch.mts', 'Actual profile self-replacement then immediate root disposal without a final transaction barrier, plus interrupted startup disposal.',
               [Path(__file__).resolve(), Path(watch.__file__).resolve(), ROOT/'dsh/cordis/hmr.py', ROOT/'dsh/boot/recomposition.py'], prepare, node_args=('--expose-internals',))
