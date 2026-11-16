import asyncio
import json
import sys
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.deliverables.change_git import GitRunner, locateGitWorkspace, snapshotTree
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from scripts import rc022_change_git_probe as corpus


@pytest.mark.asyncio
async def test_real_git_snapshots_are_private_and_match_original_tree_blob_diff_contract(tmp_path):
    corpus.prepare(tmp_path)
    result = (await corpus.observe())[0]
    assert result['untouched'] and result['indexScratch'] == []
    assert result['before'] != result['after']
    listing = {row['path']: row for row in result['listing']}
    assert listing['renamed.txt']['oldPath'] == 'rename.txt'
    assert listing['tracked.txt']['added'] == 2
    assert 'ignored.txt' not in listing and result['ignored'] == ['ignored.txt']
    contents = {row['path']: row for row in result['contents']}
    assert contents['tracked.txt']['before']['text'] == 'baseline unstaged\n'
    assert contents['literal[1].txt']['before']['text'] == 'literal\n'
    assert contents['untracked.txt']['after'] is None
    assert contents['scratch']['before'] is None and contents['scratch']['after'] is None
    assert result['cap'] == 'git diff-tree output exceeded the configured cap'
    (tmp_path/'git-snapshot-observations.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['timeout', 'abort', 'cancel'])
async def test_git_runner_joins_real_process_and_withdraws_timer_signal_on_failure(tmp_path, action):
    ctx = Context()
    await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    controller = AbortController()
    runner = GitRunner(ctx.subprocess, sys.executable,
        dict(timeoutMs=50 if action == 'timeout' else 10000, outputMaxBytes=1024))
    pending = asyncio.create_task(runner.run(['-c', 'import time; time.sleep(10)'],
        dict(cwd=str(tmp_path), signal=controller.signal)))
    try:
        if action != 'timeout':
            for _ in range(1000):
                if ctx.subprocess.live:
                    break
                await asyncio.sleep(.001)
            assert ctx.subprocess.live
            if action == 'abort':
                controller.abort(RuntimeError('controlled'))
            else:
                pending.cancel()
        with pytest.raises(asyncio.CancelledError if action == 'cancel' else RuntimeError) as raised:
            await pending
        if action != 'cancel':
            assert ('timed out after 50ms' if action == 'timeout' else 'was aborted') in str(raised.value)
        assert not controller.signal._listeners
        assert not ctx.subprocess.live
        assert not ctx.subprocess.ordinary_cleanups
    finally:
        if not pending.done():
            controller.abort()
            await asyncio.gather(pending, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_missing_repository_and_empty_index_preserve_source_state(tmp_path):
    ctx = Context()
    await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    runner = GitRunner(ctx.subprocess, 'git', dict(timeoutMs=30000, outputMaxBytes=1048576))
    outside = tmp_path/'outside'
    outside.mkdir()
    scratch_calls = []
    async def scratch():
        scratch_calls.append(True)
        return str(tmp_path/'private')
    try:
        # Explicitly isolate from this test checkout's enclosing repository.
        original = runner.run
        async def isolated(args, options):
            return await original(args, dict(options, env=dict(options.get('env') or {}, GIT_CEILING_DIRECTORIES=str(tmp_path))))
        runner.run = isolated
        assert await locateGitWorkspace(runner, str(outside), scratch, NEVER_ABORTED) is None
        assert scratch_calls == []
        corpus.git(outside, 'init', '-q')
        before = corpus.repo_state(outside)
        (outside/'new.txt').write_bytes(b'untracked\n')
        workspace = await locateGitWorkspace(runner, str(outside), scratch, NEVER_ABORTED)
        tree = await snapshotTree(runner, workspace, NEVER_ABORTED)
        assert len(tree) == 40 and before == corpus.repo_state(outside)
        assert not (outside/'.git'/'index').exists()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_private_snapshot_preserves_unmerged_index_and_repository_objects(tmp_path):
    import subprocess
    corpus.git(tmp_path, 'init', '-q', '-b', 'main')
    corpus.git(tmp_path, 'config', 'user.name', 'Fixture')
    corpus.git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    file = tmp_path/'conflict.txt'
    file.write_bytes(b'base\n')
    corpus.git(tmp_path, 'add', '--all')
    corpus.git(tmp_path, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'base')
    corpus.git(tmp_path, 'checkout', '-qb', 'side')
    file.write_bytes(b'side\n')
    corpus.git(tmp_path, '-c', 'commit.gpgsign=false', 'commit', '-qam', 'side')
    corpus.git(tmp_path, 'checkout', '-q', 'main')
    file.write_bytes(b'main\n')
    corpus.git(tmp_path, '-c', 'commit.gpgsign=false', 'commit', '-qam', 'main')
    with pytest.raises(subprocess.CalledProcessError):
        corpus.git(tmp_path, '-c', 'commit.gpgsign=false', 'merge', 'side')
    before = corpus.repo_state(tmp_path)
    ctx = Context()
    await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    runner = GitRunner(ctx.subprocess, 'git', dict(timeoutMs=30000, outputMaxBytes=1048576))
    try:
        workspace = await locateGitWorkspace(runner, str(tmp_path), lambda: str(tmp_path/'private'), NEVER_ABORTED)
        tree = await snapshotTree(runner, workspace, NEVER_ABORTED)
        assert len(tree) == 40 and before == corpus.repo_state(tmp_path)
        assert b'UU conflict.txt' in corpus.git(tmp_path, 'status', '--porcelain')
        assert not list(Path(workspace['scratch']).glob('index-*'))
    finally:
        await ctx.fiber.dispose()
