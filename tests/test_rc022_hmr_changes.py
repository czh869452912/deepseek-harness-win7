import pytest

from scripts.rc022_hmr_changes_probe import cases, observe


@pytest.mark.asyncio
async def test_evaluated_graph_cycles_and_exclusion_boundaries():
    rows = await observe(cases()[:6])
    assert rows == [
        dict(accepted=[], declined=[]),
        dict(accepted=['changed'], declined=['leaf']),
        dict(accepted=['changed', 'cycle'], declined=[]),
        dict(accepted=['changed'], declined=['left', 'right']),
        dict(accepted=['changed'], declined=['external']),
        dict(accepted=['changed', 'first', 'second'], declined=[]),
    ]
