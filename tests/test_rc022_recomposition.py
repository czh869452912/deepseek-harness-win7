import asyncio
import contextlib
import io
import json
from pathlib import Path
import pytest
from dsh.boot import boot, recompose_profile, PluginPackages, create_runtime_resolution
from dsh.boot.app_boot import _bootstrap_includes
from scripts import rc022_recompose_probe as probe


def test_complete_generation_order_and_recovery(tmp_path):
    probe.OUTPUT = tmp_path
    rows = {row['mode']: row for row in asyncio.run(probe.native())}
    assert len(rows) == 10
    for name in ('remove', 'held', 'group'):
        assert rows[name]['trace'] == ['stop-old', 'publish']
        assert not rows[name]['candidate'] and rows[name]['reload'] == [[]]
    assert rows['held']['settled_before'] is False
    assert rows['unchanged']['old_table'] and rows['unchanged']['trace'] == []
    assert rows['retry']['active'] and rows['retry']['same_entry']
    assert rows['running']['active'] and not rows['running']['same_fiber']
    assert rows['running-failed']['fatal'] and rows['running-failed']['reload'] == []
    for name in ('restart', 'publish-error'):
        assert rows[name]['trace'] == ['stop-old', 'publish', 'start']
        assert rows[name]['active'] and rows[name]['old_table']
    assert rows['restart']['restart'] == 'package-moved'
    assert rows['publish-error']['fatal'] and rows['read-error']['fatal']
    assert rows['read-error']['trace'] == []


@pytest.mark.asyncio
async def test_tree_root_and_group_ownership_survive_nested_group_construction(tmp_path):
    path = tmp_path / 'root.json'; path.write_text('[]', encoding='utf-8')
    row = dict(id='group', name='cordis:group', group=True, config=[dict(id='child', name='cordis:healthy')])
    def setup(ctx): ctx.loader.builtins['healthy'] = lambda owner, config: None
    ctx = await boot('probe', str(path), [dict(insert=[row])], setup)
    try:
        include = _bootstrap_includes.get(ctx)
        group = next(row for row in ctx.loader.entries() if row.options['id'] == 'group')
        child = next(row for row in ctx.loader.entries() if row.options['id'] == 'child')
        assert include.subgroup is include.subtree.root
        assert group.parent is include.subgroup
        assert child.parent is group.subgroup
        assert child.parent.tree is include.subgroup.tree
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_preapply_restart_restores_multiple_rows_in_original_group_positions(tmp_path):
    options, path = probe.fixture(tmp_path)
    table = await create_runtime_resolution(options)
    def setup(ctx):
        PluginPackages(ctx, dict(resolution=table))
        ctx.loader.builtins['healthy'] = lambda owner, config: None
    children = [dict(id=name, name='cordis:healthy') for name in ('a', 'b', 'c', 'd')]
    patches = [dict(insert=[dict(id='group', name='cordis:group', group=True, config=children)])]
    ctx = await boot('probe', str(path), patches, setup)
    try:
        anchor = Path(options['installAnchor']); manifest = json.loads(anchor.read_text(encoding='utf-8'))
        manifest['version'] = '2.0.0'; anchor.write_text(json.dumps(manifest), encoding='utf-8')
        next_patches = [dict(insert=[dict(id='group', name='cordis:group', group=True, config=[children[1], children[3]])])]
        assert await recompose_profile(ctx, next_patches, 'probe') == dict(warnings=[], restartReason='package-moved')
        group = next(row for row in ctx.loader.entries() if row.options['id'] == 'group')
        assert [row['id'] for row in group.subgroup.data] == ['a', 'b', 'c', 'd']
        assert all(group.subgroup.get(name).fiber.state == 2 for name in ('a', 'b', 'c', 'd'))
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_applied_generation_failure_is_not_rolled_back(tmp_path):
    path = tmp_path / 'root.json'; path.write_text('[]', encoding='utf-8')
    def setup(ctx):
        ctx.loader.builtins['healthy'] = lambda owner, config: None
        def fail(owner, config): raise RuntimeError('new failure')
        ctx.loader.builtins['broken'] = fail
    ctx = await boot('probe', str(path), [dict(insert=[dict(id='old', name='cordis:healthy')])], setup)
    try:
        with contextlib.redirect_stderr(io.StringIO()), pytest.raises(RuntimeError, match='new failure'):
            await recompose_profile(ctx, [dict(insert=[dict(id='new', name='cordis:broken')])], 'probe')
        ids = {row.options['id'] for row in ctx.loader.entries()}
        assert 'old' not in ids and 'new' in ids
    finally: await ctx.fiber.dispose()
