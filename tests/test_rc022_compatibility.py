import asyncio
import json
import os
from pathlib import Path
import stat
import pytest
from dsh.boot import plugin_compatibility as plugin, profile_compatibility as profile
from dsh.boot.semver import satisfies, is_exact_version


@pytest.mark.parametrize('requirement', ['*', '^0.1.0', '~0.1.0', '>=0.1.0 <0.2.0',
    '0.1.x', '0.1.0 - 0.1.9', '^0.2.0 || ^0.1.0', '0.1.7-alpha.1'])
def test_prerelease_ranges_are_included(requirement):
    assert satisfies('0.1.7-alpha.1', requirement)


@pytest.mark.parametrize('requirement', ['^0.2.0', '>=0.1.7', 'broken', '', ' ',
    'workspace:>=0.2.0', 'file:../dsh', 'npm:dsh@*', 'v=0.1.7-alpha.1'])
def test_invalid_and_unmet_ranges_fail_closed(requirement):
    assert not satisfies('0.1.7-alpha.1', requirement)


def test_engine_precedence_peer_validation_and_exact_exemptions():
    identity = dict(name='@scope/plugin', version='2.0.0')
    runtime = plugin.get_dsh_runtime_version()
    assert plugin.evaluate_plugin_compatibility(dict(identity, engines={'dsh': '*'}, peerDependencies=None)) is None
    manifest = dict(identity, engines={'dsh': '^99'}, peerDependencies={'@deepseek-ai/dsh': '*'})
    issue = plugin.evaluate_plugin_compatibility(manifest, {'@scope/plugin@2.0.0': [runtime]})
    assert issue['requirements'] == {'engines.dsh': '^99'} and issue['exempted']
    assert not plugin.evaluate_plugin_compatibility(manifest, {'@scope/plugin@2.0.0': ['*']})['exempted']
    assert 'Exact-version exemption: active.' in plugin.plugin_compatibility_warning(issue)
    assert plugin.evaluate_plugin_compatibility({'engines': {'dsh': '*'}}) is None
    for requirement in ('workspace:^', 'workspace:~', 'workspace:*'):
        assert plugin.evaluate_plugin_compatibility({'peerDependencies': {'@deepseek-ai/dsh-session': requirement}}) is None
    with pytest.raises(ValueError, match='must be a string'):
        plugin.evaluate_plugin_compatibility({'peerDependencies': {'unrelated': 1}})


@pytest.mark.parametrize('field', ['engines', 'peerDependencies'])
@pytest.mark.parametrize('value', [None, [], 'bad', 1, False])
def test_malformed_requirement_containers_are_rejected(field, value):
    with pytest.raises(ValueError, match=field+' must be an object'):
        plugin.evaluate_plugin_compatibility({field: value})


@pytest.mark.parametrize('version', ['1.2.3', '1.2.3-alpha.1', '1.2.3+build.7', '1.2.3-alpha+build'])
def test_canonical_version_identity(version):
    assert is_exact_version(version)
    profile.validate_plugin_version_exemption('@scope/plugin@'+version, version)


@pytest.mark.parametrize('package,version', [('plugin','1.2.3'),('plugin@^1.2.3','1.2.3'),
    ('plugin@v1.2.3','1.2.3'),('plugin@1.2.3','*'),('plugin@1.2.3',' 1.2.3'),('../plugin@1.2.3','1.2.3')])
def test_noncanonical_grants_are_rejected(package, version):
    with pytest.raises(ValueError, match='exact'):
        profile.validate_plugin_version_exemption(package, version)


@pytest.mark.asyncio
async def test_profile_grants_are_independent_locked_and_repair_required(tmp_path):
    directory = str(tmp_path/'nested'); runtime = plugin.get_dsh_runtime_version()
    assert profile.read_profile_compatibility(directory) == dict(exemptions={}, warnings=[], rewritable=True)
    with pytest.raises(ValueError, match='crashes or data loss'):
        await profile.set_profile_version_exemption(directory, 'plugin@1.0.0', runtime, True, False)
    with pytest.raises(ValueError, match='runs DSH'):
        await profile.set_profile_version_exemption(directory, 'plugin@1.0.0', '9.9.9', True, True)
    await asyncio.gather(*[profile.set_profile_version_exemption(directory, name+'@1.0.0', runtime, True, True)
        for name in ('first', 'second', 'first')])
    path = Path(directory)/'compatibility.json'
    assert profile.read_profile_version_exemptions(directory) == {'first@1.0.0': [runtime], 'second@1.0.0': [runtime]}
    if os.name != 'nt':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    await profile.set_profile_version_exemption(directory, 'first@1.0.0', '0.0.1', False, False)
    await profile.set_profile_version_exemption(directory, 'first@1.0.0', runtime, False, False)
    assert profile.read_profile_version_exemptions(directory) == {'second@1.0.0': [runtime]}
    malformed = json.dumps({'good@1.0.0': [runtime], 'bad@*': [runtime]})
    path.write_text(malformed, encoding='utf-8')
    read = profile.read_profile_compatibility(directory)
    assert read['exemptions'] == {'good@1.0.0': [runtime]} and not read['rewritable']
    for enabled in (True, False):
        with pytest.raises(ValueError, match='must be repaired'):
            await profile.set_profile_version_exemption(directory, 'good@1.0.0', runtime, enabled, True)
        assert path.read_text(encoding='utf-8') == malformed
    assert not list(Path(directory).glob('*.tmp')) and not list(Path(directory).glob('*.lock'))
    assert not (Path(directory)/'package.json').exists()


@pytest.mark.parametrize('value', [[], None, 'all', 1, {'plugin@1.2.3': '1.2.3'},
    {'plugin@1.2.3': [1]}, {'plugin@1.2.3': ['^1.2.3']}])
def test_damaged_permissions_do_not_authorize_or_abort_profile(tmp_path, value):
    (tmp_path/'compatibility.json').write_text(json.dumps(value), encoding='utf-8')
    read = profile.read_profile_compatibility(str(tmp_path))
    assert read['exemptions'] == {} and not read['rewritable'] and len(read['warnings']) == 1


def test_unreadable_and_malformed_permission_files_are_diagnostics(tmp_path):
    path = tmp_path/'compatibility.json'; path.mkdir()
    assert 'cannot be read' in profile.read_profile_compatibility(str(tmp_path))['warnings'][0]
    path.rmdir(); path.write_bytes(b'{\xff')
    assert 'is not valid JSON' in profile.read_profile_compatibility(str(tmp_path))['warnings'][0]


@pytest.mark.asyncio
async def test_failed_publication_keeps_permissions_and_cleans_stage(tmp_path, monkeypatch):
    from dsh.boot import python_plugins
    runtime = plugin.get_dsh_runtime_version()
    await profile.set_profile_version_exemption(str(tmp_path), 'plugin@1.0.0', runtime, True, True)
    path = tmp_path/'compatibility.json'; original = path.read_bytes()
    def fail(*args):
        raise OSError('publish denied')
    monkeypatch.setattr(python_plugins, '_replace_atomic_file', fail)
    with pytest.raises(OSError, match='publish denied'):
        await profile.set_profile_version_exemption(str(tmp_path), 'other@1.0.0', runtime, True, True)
    assert path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ['compatibility.json']
