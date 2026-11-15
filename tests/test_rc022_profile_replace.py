import asyncio
import json
from pathlib import Path
import pytest
from dsh.boot.profile import init_profile, create_symlink
from dsh.boot.profile_boot import initialize_profile_from_default
from dsh.boot.profile_lease import ProfileLease
from scripts import rc022_profile_replace_probe as probe


def test_real_replacement_restoration_and_concurrent_winner_journeys(tmp_path):
    probe.prepare(tmp_path)
    rows = asyncio.run(probe.native())
    assert len(rows) == 22
    modes = {case.get('mode'):row for case,row in zip(probe.CASES,rows) if 'mode' in case}
    assert modes['existing']['error'] is None
    assert not any(path.endswith('old-marker') for path in modes['existing']['files'])
    assert modes['new-rename']['files']['profiles/rescue/old-marker'] == 'old'
    assert modes['restore']['members'] == 2
    assert 'profiles/.rescue.staging-$ID/previous/old-marker' in modes['restore']['files']
    assert modes['concurrent']['error'] == 'concurrent'
    assert modes['concurrent']['files']['profiles/rescue/package.json']['dsh']['profile']['bundles'] == ['concurrent-bundle']
    assert modes['cleanup']['warning']


def test_active_python_profile_lease_prevents_replacement(tmp_path):
    directory = tmp_path/'profiles/rescue'
    init_profile(str(directory), ['existing-bundle'])
    before = (directory/'package.json').read_bytes()
    with ProfileLease(str(directory)):
        with pytest.raises((OSError,RuntimeError)):
            initialize_profile_from_default('rescue','web',str(tmp_path))
        assert (directory/'package.json').read_bytes() == before
        assert not list(directory.parent.glob('.rescue.staging-*'))
    initialize_profile_from_default('rescue','web',str(tmp_path))
    assert (directory/'package.json').read_bytes() != before


def test_replacement_cleans_old_dependency_junctions_without_touching_targets(tmp_path):
    directory = tmp_path/'profiles/rescue'
    init_profile(str(directory), [])
    external = tmp_path/'external'; external.mkdir()
    (external/'keep').write_text('user dependency',encoding='utf-8')
    modules = directory/'node_modules'; modules.mkdir()
    create_symlink(str(external),str(modules/'linked'))
    initialize_profile_from_default('rescue','web',str(tmp_path))
    assert (external/'keep').read_text(encoding='utf-8') == 'user dependency'
    assert not (directory/'node_modules').exists()
    assert not list(directory.parent.glob('.rescue.staging-*'))
