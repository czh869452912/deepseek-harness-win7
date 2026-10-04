import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(sys.argv[sys.argv.index('--root') + 1]).resolve() if '--root' in sys.argv else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.session.sqlite_store import SqliteStore
from dsh.session.sqlite_database import DatabaseError


async def observe(path):
    assert not path.exists()
    meta = dict(id='locked', version=0, createdAt=1)
    store = SqliteStore(str(path), busy_timeout_ms=100)
    peer = None
    try:
        await store.append_batch(meta, [dict(type='turn/start', seq=0, time=0, data=dict(turn=1))], False)
        peer = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('sqlite_store_lock_peer.py')), '--root', str(ROOT),
                                 '--path', str(path), '--mode', 'hold'], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        assert json.loads(peer.stdout.readline()) == dict(held=True)
        before = await store.read_revision(meta['id'])
        started = time.monotonic()
        try:
            await store.append_batch(meta, [dict(type='turn/end', seq=1, time=1, data=dict(turn=1))], True)
            raise AssertionError('competing reservation ignored')
        except DatabaseError as error:
            assert error.code == 5
        elapsed = time.monotonic() - started
        assert elapsed < 2 and await store.read_revision(meta['id']) == before
        peer.stdin.write('\n')
        peer.stdin.flush()
        output, errors = peer.communicate(timeout=10)
        assert peer.returncode == 0 and not errors
        peer = None
        result = subprocess.run([sys.executable, '-I', str(Path(__file__).with_name('sqlite_store_lock_peer.py')), '--root', str(ROOT),
                                 '--path', str(path), '--mode', 'append'], capture_output=True, text=True, encoding='utf-8', timeout=10)
        assert result.returncode == 0 and not result.stderr
        try:
            await store.commit_repair(meta, None, [dict(type='turn/end', seq=1, time=1, data=dict(turn=1))])
            raise AssertionError('stale repair overwrote the winning peer')
        except ValueError as error:
            assert str(error) == 'session locked repair is stale: closer starts at seq 1, stored next seq is 2'
        loaded = await store.load_stored(meta['id'])
        assert len(loaded['events']) == 2
        return dict(crossProcessBusyCode=5, revisionUnchangedWhileBlocked=True, finiteBudget=elapsed < 2,
                             staleRepairRefused=True, winningTailRetained=True)
    finally:
        if peer is not None:
            peer.communicate(input='\n', timeout=10)
        await store.close()



