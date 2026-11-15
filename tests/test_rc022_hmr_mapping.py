import asyncio

import pytest

from scripts.rc022_hmr_mapping_probe import observe


@pytest.mark.asyncio
async def test_live_namespaces_survive_changed_package_exports_and_disabled_shadows(tmp_path):
    rows = await asyncio.wait_for(observe(tmp_path/'package-mappings'), 15)
    assert len(rows) == 10
    assert all(row['trace'] == [] and row['first_same'] for row in rows if row['step'] == 'mapping')
    old = next(row for row in rows if row['mode'] == 'two-active' and row['step'] == 'old-source')
    assert old['trace'] == ['stop:a:one', 'start:a-edited:one']
    assert not old['first_same'] and old['second_same']
    new = next(row for row in rows if row['step'] == 'new-source')
    assert new['trace'] == ['stop:b:two', 'start:b-edited:two'] and not new['shared']
    assert all(row['shadow_inactive'] for row in rows if row['step'] == 'old-source')
    assert rows[-1] == dict(mode='disabled-reenable', step='reenable', trace=['start:b:one'])
