import asyncio
import builtins
import json
from pathlib import Path
import pytest
from scripts import rc022_profile_layers_probe as probe
from dsh.boot.profile import bundle_patch_files, bundle_patch_paths, load_profile_directory
from dsh.boot.bundle_platform import assert_bundle_platform, UnsupportedBundlePlatformError


def test_real_bundle_files_skip_independently_and_preserve_manifest(tmp_path):
    probe.OUTPUT = tmp_path
    results = asyncio.run(probe.native())
    modes = {row['mode']:row for row in results if 'mode' in row}
    assert len(results) == 53
    assert modes['user-broken']['error']
    for mode in ('ordinary','grant','bundles-only','retired'):
        row = modes[mode]
        assert not row['error'] and row['silent']
        assert [layer['name'] for layer in row['layers']] == (['multi','guarded','kept'] if mode == 'grant' else ['multi','kept'])
        assert row['entries'][0]['config']['value'] == (2 if mode == 'bundles-only' else 3)
        assert row['entries'][0]['name'].endswith('/multi/local.mjs')
        assert row['entries'][1]['name'].endswith('/multi/layers/local.mjs')
        # Parser diagnostics retain their own line breaks in the one report per bundle.
        assert row['report_lines'] >= len(row['skipped'])
        assert row['unchanged'] == (mode != 'retired')
        assert row['manifest']['preserved'] == 'yes'
    assert all(not name.endswith('bundle') for name in modes['retired']['manifest']['dsh']['profile']['bundles'] if name.startswith('@deepseek-ai'))


@pytest.mark.parametrize('value', [None, 1, {}, [1], ['valid', None]])
def test_bundle_patch_declaration_must_be_string_or_list_of_strings(value):
    with pytest.raises(ValueError,match='file path or a list'):
        bundle_patch_files(dict(patch=value))


def test_bundle_patch_empty_list_and_order_and_platform_omission(tmp_path):
    assert bundle_patch_files(dict(patch=[])) == []
    assert bundle_patch_paths(str(tmp_path),dict(patch=['./first.yml','./layers/second.yml'])) == [str(tmp_path/'first.yml'),str(tmp_path/'layers/second.yml')]
    assert_bundle_platform()
    assert_bundle_platform(['wsl'], 'linux',dict(env={},osRelease='5.15-Microsoft-standard'))
    with pytest.raises(UnsupportedBundlePlatformError):
        assert_bundle_platform(['wsl'],'win32',dict(env={'WSL_INTEROP':'yes'},osRelease='Microsoft'))


def test_invalid_profile_manifest_is_fatal_and_user_layer_can_be_skipped(tmp_path):
    directory = tmp_path/'profile';directory.mkdir()
    manifest = directory/'package.json';manifest.write_text('[]',encoding='utf-8')
    with pytest.raises(RuntimeError,match='must hold a JSON object'):
        load_profile_directory('test',str(directory),str(tmp_path/'package.json'))
    manifest.write_text('{}',encoding='utf-8')
    (directory/'cordis.patch.yml').write_text('[',encoding='utf-8')
    assert load_profile_directory('test',str(directory),str(tmp_path/'package.json'),dict(userLayer=False)).layers == []
    with pytest.raises(Exception):
        load_profile_directory('test',str(directory),str(tmp_path/'package.json'))


def test_profile_root_write_failure_propagates(tmp_path, monkeypatch):
    from dsh.boot import profile_boot
    directory=tmp_path/'profiles'/'empty';directory.mkdir(parents=True)
    (directory/'package.json').write_text('{}',encoding='utf-8')
    original = builtins.open
    def guard(path,*args,**kwargs):
        if str(path)==str(directory/'cordis.yml'):
            raise PermissionError('root write refused')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(builtins,'open',guard)
    with pytest.raises(PermissionError,match='root write refused'):
        profile_boot.prepare_profile('empty',dsh_home=str(tmp_path))
