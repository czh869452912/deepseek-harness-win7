import asyncio
import json

import pytest

from dsh.llm.deepseek_upload_index_current import DeepSeekUploadIndex
from scripts import rc022_upload_index_probe as corpus


@pytest.mark.asyncio
async def test_durable_generation_transitions_and_canonical_bytes(tmp_path):
    rows = await corpus.observe(tmp_path/'files')
    (tmp_path/'upload-index-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 46
    indexes = [row for row in rows if 'events' in row]
    assert len(indexes) == 28
    assert all(row['leftovers'] == ['index.json'] for row in indexes)
    assert all(row['events'][-2]['text'].find('successor') >= 0 for row in indexes)
    assert all(json.loads(row['events'][-1]['text']) == dict(formatVersion=3, records=[]) for row in indexes)


@pytest.mark.asyncio
async def test_shared_path_winner_and_single_batch_invalidation(tmp_path):
    path = str(tmp_path/'index.json'); first = DeepSeekUploadIndex(path); second = DeepSeekUploadIndex(path)
    candidates = [corpus.record(fileId='upload-'+str(index)) for index in range(8)]
    outcomes = await asyncio.gather(*(store.commit(candidate, 1000, 2)
        for store, candidate in zip([first, second]*4, candidates)))
    assert sum(row['accepted'] for row in outcomes) == 1
    winner = outcomes[0]['record']['fileId']
    assert all(row['record']['fileId'] == winner for row in outcomes)
    variant = 'sha256:'+'f'*64
    await second.commit(corpus.record(variantId=variant, fileId='second'), 1000, 2)
    writes = []; save = first._save
    first._save = lambda records: (writes.append(records), save(records))[1]
    await first.remove('a'*64, [dict(variantId='sha256:'+'c'*64, fileId='stale'),
                              dict(variantId=variant, fileId='second')])
    assert len(writes) == 1
    assert (await first.get('a'*64, 'sha256:'+'c'*64, 1000, 2))['fileId'] == winner
    assert await first.get('a'*64, variant, 1000, 2) is None
    await first.remove('a'*64, [])
    assert len(writes) == 1


@pytest.mark.asyncio
async def test_filesystem_errors_propagate_and_leave_no_lock(tmp_path):
    directory = tmp_path/'index.json'; directory.mkdir()
    store = DeepSeekUploadIndex(str(directory))
    with pytest.raises(OSError): await store.get('a'*64, 'sha256:'+'c'*64, 0, 0)
    with pytest.raises(OSError): await store.commit(corpus.record(), 0, 0)
    assert not (tmp_path/'index.json.lock').exists()


@pytest.mark.asyncio
async def test_transient_windows_replace_failure_retries_inside_the_same_lock(tmp_path, monkeypatch):
    import os
    from dsh.util import atomic_write
    if os.name != 'nt': pytest.skip('Windows sharing violation')
    original = atomic_write.os.replace; attempts = []
    def replace(source, destination):
        attempts.append((source, destination))
        assert (tmp_path/'index.json.lock').exists()
        if len(attempts) == 1: raise PermissionError(13, 'temporary sharing violation')
        return original(source, destination)
    monkeypatch.setattr(atomic_write.os, 'replace', replace)
    store = DeepSeekUploadIndex(str(tmp_path/'index.json'))
    result = await store.commit(corpus.record(), 0, 0)
    assert result['accepted'] and len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert sorted(path.name for path in tmp_path.iterdir()) == ['index.json']
