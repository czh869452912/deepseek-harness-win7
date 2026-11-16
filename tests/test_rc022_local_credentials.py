import json

import pytest

from scripts.rc022_local_credentials_probe import observe


@pytest.mark.asyncio
async def test_managed_credential_reference_and_preview_corpus(tmp_path):
    rows = await observe(tmp_path/'files')
    (tmp_path/'local-credentials-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 60
    for row in rows:
        initial, saved, removed, absent, rejected = row['result']
        assert initial['events'] == []
        assert saved['value']['source'] == 'file' and saved['info']['writable'] is True
        assert saved['info']['masked'] != saved['value']['value']
        assert 'masked' not in removed['info']
        assert absent == removed
        assert absent['events'] == ['TEST_KEY', 'TEST_KEY']
        assert row['refs'] == {}
        assert rejected['error'].endswith('; use unset')
