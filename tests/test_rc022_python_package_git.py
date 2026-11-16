import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

from dsh.boot.python_package_git import (create_git_workspace, cleanup_git_workspace,
    git_source, _safe_diagnostic)
from dsh.boot.plugin_package_run import run_package_process
from dsh.boot.python_package_tarball import unpack_tarball
from dsh.boot.python_plugins import file_hashes, validate_package
from dsh.core.abort import AbortController
from test_python_plugin_distribution import profile, EXAMPLE, PACKAGE, ROOT


@pytest.fixture
def repository(tmp_path):
    executable = shutil.which('git')
    assert executable, 'the Git preparation qualification requires actual Git'
    source = tmp_path / 'Git source with spaces'
    source.mkdir()
    shutil.copytree(str(EXAMPLE), str(source / 'plugin'), ignore=shutil.ignore_patterns('__pycache__'))
    sentinel = tmp_path / 'author-code-executed'
    code = source / 'plugin/python/echo/plugin.py'
    code.write_text('from pathlib import Path\nPath(' + repr(str(sentinel)) + ').touch()\n' + code.read_text(encoding='utf-8'), encoding='utf-8')
    commands = []
    def git(*args):
        command = [executable, '-c', 'core.hooksPath=' + str(tmp_path / 'empty-hooks'),
            '-c', 'commit.gpgSign=false', '-c', 'core.autocrlf=false', '-C', str(source)] + list(args)
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        commands.append(dict(argv=command, output=result.stdout.decode('utf-8', errors='replace')))
        return result.stdout.decode('utf-8').strip()
    git('init', '--initial-branch=main')
    git('config', 'user.name', 'Git preparation qualification')
    git('config', 'user.email', 'native-git@example.invalid')
    git('add', '.')
    git('commit', '-m', 'reviewed native plugin')
    commit = git('rev-parse', 'HEAD')
    git('tag', 'reviewed')
    try:
        yield dict(source=source, commit=commit, sentinel=sentinel, git=git,
            spec='git+' + source.as_uri(), commands=commands)
    finally:
        (tmp_path / 'git-seed-observation.json').write_text(json.dumps(dict(commit=commit, commands=commands), indent=2), encoding='utf-8')
        # Only this fixture's single-link object files can have attributes reset.
        for path in (source / '.git/objects').rglob('*'):
            if path.is_file():
                info = path.lstat()
                assert info.st_nlink == 1 and not path.is_symlink()
                if not info.st_mode & stat.S_IWRITE:
                    os.chmod(str(path), info.st_mode | stat.S_IWRITE)


async def prepare(directory, tmp_path, spec, options=None, limits=''):
    owned = tmp_path / 'captured-owner'
    owned.mkdir()
    output = owned / 'output'
    output.mkdir()
    workspace = create_git_workspace(str(owned))
    worker = owned / 'worker.py'
    worker.write_text('import sys\nsys.path.insert(0,' + repr(str(ROOT)) + ')\n'
        'from dsh.boot.python_package_git import publish_git\n'
        'from dsh.boot import python_package_git as provider\n' + limits + '\n'
        'from dsh.boot.python_package_query import PackageQueryError\n'
        'try:\n publish_git(*sys.argv[1:])\n'
        'except (PackageQueryError, ValueError) as error:\n print(getattr(error,"code","ERR_DSH_GIT_SOURCE"),str(error),flush=True);sys.exit(1)\n', encoding='utf-8')
    options = dict(options or {})
    options['env'] = dict(options.get('env') or {}, TEMP=str(owned), TMP=str(owned), TMPDIR=str(owned))
    options['outputBytes'] = 16384
    try:
        result = await run_package_process(str(directory), [sys.executable, str(worker), str(directory), spec, str(output), workspace], options)
    finally:
        cleanup_git_workspace(workspace)
    assert not Path(workspace).exists() and not list(directory.rglob('run.json'))
    return result, output


@pytest.mark.asyncio
@pytest.mark.parametrize('ref', ['commit', 'reviewed', 'main', 'HEAD'])
async def test_actual_captured_git_resolves_commit_and_subdirectory_without_running_author_code(profile, repository, tmp_path, ref):
    _, directory = profile
    before = (directory / 'package.json').read_bytes()
    selector = repository['commit'] if ref == 'commit' else ref
    result, output = await prepare(directory, tmp_path, repository['spec'] + '#' + selector + '&path:plugin')
    assert result['exitCode'] == 0, result
    value = json.loads((output / 'prepared.json').read_text(encoding='utf-8'))
    assert value['formatVersion'] == 3 and value['acquisition'] is None
    assert value['git'] == dict(repository=repository['source'].as_uri(), commit=repository['commit'], directory='plugin')
    archive = (output / 'package.tgz').read_bytes()
    assert value['archive'] == dict(sha256=hashlib.sha256(archive).hexdigest(), bytes=len(archive))
    stage = tmp_path / 'verified'
    stage.mkdir()
    unpack_tarball(str(output / 'package.tgz'), str(stage))
    assert validate_package(str(stage)) == value['manifest'] and value['manifest']['name'] == PACKAGE
    assert file_hashes(str(stage)) == value['files']
    assert not repository['sentinel'].exists() and (directory / 'package.json').read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('damage', ['commit', 'directory', 'abi', 'missing-git', 'repository-limit', 'archive-limit'])
async def test_actual_git_refuses_invalid_sources_and_resource_limits_before_commit(profile, repository, tmp_path, damage):
    _, directory = profile
    before = (directory / 'package.json').read_bytes()
    commit, package = repository['commit'], 'plugin'
    options, limits = {}, ''
    expected = 'ERR_DSH_GIT_SOURCE'
    if damage == 'commit':
        commit = '1' * 40
    elif damage == 'directory':
        package = 'missing'
    elif damage == 'abi':
        path = repository['source'] / 'plugin/package.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['dsh'].pop('python')
        path.write_text(json.dumps(value), encoding='utf-8')
        repository['git']('add', '.')
        repository['git']('commit', '-m', 'invalid Python ABI')
        commit = repository['git']('rev-parse', 'HEAD')
        expected = 'ERR_DSH_PACKAGE_VALIDATION'
    elif damage == 'missing-git':
        options = dict(env=dict(PATH=''))
        expected = 'ERR_DSH_GIT_MISSING'
    else:
        limits = 'provider.' + ('MAX_REPOSITORY_BYTES=1024' if damage == 'repository-limit' else 'MAX_ARCHIVE_BYTES=2048')
        expected = 'ERR_DSH_GIT_SIZE'
    result, output = await prepare(directory, tmp_path, repository['spec'] + '#' + commit + '&path:' + package, options, limits)
    assert result['exitCode'] != 0 and expected in result['output'], result
    assert not (output / 'prepared.json').exists() and not repository['sentinel'].exists()
    assert (directory / 'package.json').read_bytes() == before and not (directory / 'node_modules' / PACKAGE).exists()


@pytest.mark.asyncio
async def test_actual_git_cancel_drains_captured_tree_before_readonly_object_cleanup(profile, repository, tmp_path):
    _, directory = profile
    before = (directory / 'package.json').read_bytes()
    controller = AbortController()
    result, output = await asyncio.wait_for(prepare(directory, tmp_path,
        repository['spec'] + '#' + repository['commit'] + '&path:plugin',
        dict(signal=controller.signal, onOutput=lambda text, stream: controller.abort() if 'Archiving Git commit' in text else None)), 15)
    assert controller.signal.aborted
    assert not repository['sentinel'].exists() and (directory / 'package.json').read_bytes() == before


def test_git_source_normalization_and_diagnostic_redaction():
    value = git_source('github:owner/repo#' + 'A' * 40 + '&path:plugins%2Fecho')
    assert value == dict(repository='https://github.com/owner/repo.git', publicRepository='https://github.com/owner/repo.git', ref='a' * 40, directory='plugins/echo')
    value = git_source('git+https://user:secret@example.invalid/owner/repo.git#main')
    diagnostic = _safe_diagnostic('fatal: https://user:secret@example.invalid/owner/repo.git?token=secret /owned', value, '/owned')
    assert 'secret' not in diagnostic and 'user:' not in diagnostic and '/owned' not in diagnostic
    for spec in ('github:owner/repo#main&path:../escape', 'github:owner/repo#--upload-pack=other', 'github:owner/repo#one&two'):
        with pytest.raises(ValueError):
            git_source(spec)


def test_owned_git_cleanup_refuses_shared_objects_then_clears_owned_readonly_object(tmp_path):
    workspace = Path(create_git_workspace(str(tmp_path)))
    objects = workspace / 'repository/objects/aa'
    objects.mkdir(parents=True)
    original = objects / 'object'
    original.write_bytes(b'owned synthetic object')
    duplicate = tmp_path / 'shared-object'
    os.link(str(original), str(duplicate))
    try:
        with pytest.raises(RuntimeError, match='shared Git object'):
            cleanup_git_workspace(str(workspace))
        assert duplicate.stat().st_mode & stat.S_IWRITE and original.exists()
    finally:
        duplicate.unlink()
        original.chmod(stat.S_IREAD)
        cleanup_git_workspace(str(workspace))
    assert not workspace.exists()


def test_git_workspace_marker_and_unknown_external_siblings_are_preserved(tmp_path):
    workspace = Path(create_git_workspace(str(tmp_path)))
    marker = workspace / '.native-git-owner.json'
    original = marker.read_bytes()
    value = json.loads(original)
    marker.write_text(json.dumps(dict(value, owner='other-owner')), encoding='utf-8')
    with pytest.raises(ValueError, match='owner differs'):
        cleanup_git_workspace(str(workspace))
    assert workspace.exists()
    marker.write_bytes(original)
    if 'externalParent' in value:
        sibling = workspace.parent / 'unknown-asset'
        sibling.write_bytes(b'preserve until its consumer finishes')
        with pytest.raises(ValueError, match='unknown sibling'):
            cleanup_git_workspace(str(workspace))
        assert marker.exists() and sibling.exists()
        sibling.unlink()
    cleanup_git_workspace(str(workspace))
    assert not workspace.exists()
    if 'externalParent' in value:
        assert not workspace.parent.exists()
