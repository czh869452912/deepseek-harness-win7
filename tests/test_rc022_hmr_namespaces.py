import asyncio

import pytest

from scripts.rc022_hmr_namespaces_probe import observe


@pytest.mark.asyncio
async def test_reexports_keep_namespace_ownership_across_runtime_splits(tmp_path):
    rows = await asyncio.wait_for(observe(tmp_path/'namespaces'), 15)
    aliases, split, ambiguous, retained = rows
    assert aliases['shared'] and aliases['namespace_same'] == [False, False]
    assert aliases['trace'] == ['stop:shared:1:one', 'stop:shared:1:two', 'start:shared:2:one', 'start:shared:2:two']
    assert not split['shared'] and split['events'] == [1]
    assert split['trace'][-2:] == ['start:left:2:one', 'start:right:2:two']
    assert ambiguous['failed'] and ambiguous['events'] == [] and ambiguous['old_instances'] == 3
    assert ambiguous['namespace_same'] == ambiguous['cached_same'] == [True, True]
    assert retained['namespace_same'] == retained['cached_same'] == [False, True]
    assert retained['trace'][-2:] == ['start:shared:2:one', 'start:shared:1:two']
