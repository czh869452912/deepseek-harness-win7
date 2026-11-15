import pytest

from scripts.rc022_related_publication_probe import observe


@pytest.mark.asyncio
async def test_child_revision_witness_is_joined_before_preparation_and_publication(tmp_path):
    rows = await observe(tmp_path/'files')
    for row in rows:
        assert row['sourceUnchanged'] and row['stages'] == 0
        assert row['children'] == 0
        if row['name'] in ('stable', 'cancel-after-prepare', 'concurrent'):
            assert row['published'] and row['target']
            assert row['calls'] == ['related', 'verify', 'before-source-check', 'related', 'after-publication']
        else:
            assert not row['target']
            assert row['error'] == ('missing' if row['name'] == 'deleted' else 'JsonlGenerationSourceChangedError')
        if row['name'] == 'before-prepare':
            assert 'prepared' not in row and row['calls'] == ['related']
        if row['name'] == 'retry-failure':
            assert row['sameFailure'] and row['calls'].count('verify') == 1
        if row['name'] == 'concurrent':
            assert row['samePublication']
