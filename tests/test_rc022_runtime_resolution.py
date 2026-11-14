import asyncio
import json
from pathlib import Path
import pytest
from dsh.boot.runtime_resolution import create_runtime_resolution, native_package_dir
from scripts import rc022_resolution_probe as probe


def test_real_package_graphs_and_successor_recompute(tmp_path):
    probe.OUTPUT=tmp_path
    rows={row['mode']:row for row in asyncio.run(probe.native())}
    assert len(rows)==10 and all(row['unchanged'] for row in rows.values())
    assert rows['invalid']['error'] and not rows['skipped-invalid']['error']
    assert [row['name'] for row in rows['installation']['table']['entries']] == ['installation','core','peer','shared','extra']
    for mode in ('profile','other-profile','synthetic'):
        table=rows[mode]['table'];entries={row['name']:row for row in table['entries']}
        assert entries['shared']['scope']=='installation' and entries['shared']['version']=='1.0.0'
        assert entries['private']['version']==('99.0.0' if mode=='other-profile' else '1.0.0')
        assert entries['private']['scope']=='profile' and 'selected' not in entries and 'second' not in entries
        assert table['localPackageNames']==([] if mode=='synthetic' else ['selected','direct','direct','optional'])
    assert rows['linked']['table']['linkedRoots']==[dict(name='linked',realPath='$ROOT\\external' if '\\' in rows['linked']['table']['profilesDir'] else '$ROOT/external')]
    for mode in ('refresh-profile','refresh-installation'):
        assert rows[mode]['old_unchanged'] and rows[mode]['successor']!=rows[mode]['table']
    successor={row['name'] for row in rows['refresh-profile']['successor']['entries']}
    assert 'second-only' not in successor and 'new-private' in successor


@pytest.mark.asyncio
async def test_computed_table_is_detached_immutable_and_writes_nothing(tmp_path):
    options=probe.fixture(tmp_path,'profile')
    before=probe.files(tmp_path)
    table=await create_runtime_resolution(options)
    with pytest.raises(TypeError):table.profileDir='changed'
    with pytest.raises(TypeError):del table.entries
    with pytest.raises(TypeError):table.entries[0]['version']='changed'
    with pytest.raises(TypeError):table.entries[0].update(version='changed')
    detached=table.to_dict();detached['entries'][0]['version']='changed'
    assert table.entries[0]['version']=='1.0.0'
    assert probe.files(tmp_path)==before
    assert not (Path(options['home'])/'profiles/node_modules').exists()


@pytest.mark.asyncio
async def test_recompute_reads_current_disk_and_failure_keeps_previous_table(tmp_path):
    options=probe.fixture(tmp_path,'profile');table=await create_runtime_resolution(options);old=table.to_dict()
    manifest=Path(options['profile']['dir'])/'package.json';manifest.write_text('{',encoding='utf-8')
    with pytest.raises(RuntimeError,match='failed to read profile manifest'):await table.compute_latest_resolution()
    assert table.to_dict()==old and manifest.read_text(encoding='utf-8')=='{'


@pytest.mark.asyncio
async def test_missing_package_can_appear_after_an_earlier_generation(tmp_path):
    options=probe.fixture(tmp_path,'installation');first=await create_runtime_resolution(options)
    package=Path(options['installAnchor']).parent/'node_modules/uninstalled'
    assert native_package_dir(options['installAnchor'],'uninstalled') is None
    probe.package(package,'uninstalled')
    second=await first.compute_latest_resolution()
    assert 'uninstalled' not in [row['name'] for row in first.entries]
    assert 'uninstalled' in [row['name'] for row in second.entries]
