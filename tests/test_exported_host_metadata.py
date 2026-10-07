import pytest

from dsh.extensions.packaged_host import python_host_source
from scripts.oracles.exported_host_lifecycle import observe_lifecycle


@pytest.mark.asyncio
async def test_exported_host_metadata_preserves_all_mount_and_epoch_boundaries(tmp_path):
    rows = await observe_lifecycle(tmp_path)
    assert [row['name'] for row in rows] == [
        'dependency-cycle', 'dispose-while-pending', 'independent-mount-0',
        'independent-mount-1', 'initial-pending-disposal', 'late-provider',
        'modified-declaration', 'dynamic-declaration-fallback',
    ]


@pytest.mark.parametrize('declaration, expected', [
    ("plugin.inject = ['tools']", ['tools']),
    ("plugin.inject = ('tools', 'fs')", ['tools', 'fs']),
    ("plugin.inject = []", []),
    ("plugin.inject = ['']", None),
    ("plugin.inject = [4]", None),
    ("plugin.inject = list(('tools',))", None),
    ("plugin.inject = ['tools']\nother = 1", None),
], ids=['literal-list', 'literal-tuple', 'empty', 'empty-name', 'nonstring', 'dynamic', 'trailing-body'])
def test_exported_host_metadata_never_evaluates_authored_globals(tmp_path, declaration, expected):
    marker = tmp_path / 'must-not-exist'
    source = tmp_path / 'source.py'
    source.write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('ran', encoding='utf-8')\n"
                      "def plugin(ctx):\n    pass\n" + declaration + '\n', encoding='utf-8')
    plugin = python_host_source(str(source), '@probe/metadata')
    assert getattr(plugin, 'inject', None) == expected
    assert not marker.exists()


def test_client_only_export_does_not_gain_host_dependencies():
    assert getattr(python_host_source(None, '@probe/client'), 'inject', None) is None
