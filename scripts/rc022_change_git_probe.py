"""Compare real original/native Git snapshots without touching repository state."""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def git(cwd, *args):
    env = dict(os.environ, GIT_CONFIG_COUNT='0', GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
    return subprocess.check_output(['git']+list(args), cwd=str(cwd), env=env, stderr=subprocess.STDOUT)


def repo_state(repo):
    directory = repo/'.git'
    files = {}
    for part in ('index', 'HEAD', 'refs', 'objects'):
        path = directory/part
        for file in ([path] if path.is_file() else path.rglob('*') if path.exists() else []):
            if file.is_file():
                files[str(file.relative_to(directory))] = hashlib.sha256(file.read_bytes()).hexdigest()
    return files


def prepare(output):
    global OUTPUT
    OUTPUT = output
    files = output/'files'
    files.mkdir()
    for side in ('source', 'native'):
        repo = files/side
        repo.mkdir()
        git(repo, 'init', '-q')
        git(repo, 'config', 'user.name', 'Fixture')
        git(repo, 'config', 'user.email', 'fixture@example.invalid')
        git(repo, 'config', 'core.autocrlf', 'false')
        (repo/'.gitignore').write_bytes(b'ignored.txt\n')
        (repo/'tracked.txt').write_bytes(b'one\ntwo\nthree\n')
        (repo/'rename.txt').write_bytes(b'rename\n')
        (repo/'literal[1].txt').write_bytes(b'literal\n')
        (repo/'literal1.txt').write_bytes(b'other\n')
        git(repo, 'add', '--all')
        git(repo, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
        (repo/'tracked.txt').write_bytes(b'baseline unstaged\n')
        (repo/'untracked.txt').write_bytes(b'new before turn\n')
        (repo/'ignored.txt').write_bytes(b'ignored before turn\n')
    path = output/'input.json'
    path.write_text(json.dumps(dict(files=str(files))), encoding='utf-8')
    return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
    from dsh.core.abort import NEVER_ABORTED
    from dsh.deliverables.change_git import GitRunner, locateGitWorkspace, snapshotTree, diffTrees, treeBlob, blobText, ignoredPaths, gitlinkPaths
    repo = OUTPUT/'files'/'native'
    ctx = Context()
    await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    runner = GitRunner(ctx.subprocess, 'git', dict(timeoutMs=30000, outputMaxBytes=1048576))
    state = repo_state(repo)
    try:
        async def scratch():
            return str(repo/'scratch')
        workspace = await locateGitWorkspace(runner, str(repo), scratch, NEVER_ABORTED)
        before = await snapshotTree(runner, workspace, NEVER_ABORTED)
        (repo/'tracked.txt').write_bytes(b'after turn\nsecond\n')
        (repo/'rename.txt').rename(repo/'renamed.txt')
        (repo/'untracked.txt').unlink()
        (repo/'added.txt').write_bytes(b'added\n')
        (repo/'ignored.txt').write_bytes(b'ignored after turn\n')
        after = await snapshotTree(runner, workspace, NEVER_ABORTED)
        listing = await diffTrees(runner, workspace, before, after, NEVER_ABORTED)
        contents = []
        for name in ['tracked.txt', 'rename.txt', 'renamed.txt', 'added.txt', 'untracked.txt', 'ignored.txt', 'literal[1].txt', 'scratch']:
            row = dict(path=name)
            for label, tree in [('before', before), ('after', after)]:
                blob = await treeBlob(runner, workspace, tree, name, NEVER_ABORTED)
                row[label] = None if blob is None else dict(blob, text=await blobText(runner, workspace, blob['oid'], 1048576, NEVER_ABORTED))
            contents.append(row)
        truncated = GitRunner(ctx.subprocess, 'git', dict(timeoutMs=30000, outputMaxBytes=10))
        try:
            await diffTrees(truncated, workspace, before, after, NEVER_ABORTED)
            cap = 'unexpected'
        except Exception as error:
            cap = str(error)
        return [dict(before=before, after=after, listing=listing, contents=contents,
            same=await diffTrees(runner, workspace, before, before, NEVER_ABORTED),
            ignored=sorted(await ignoredPaths(runner, workspace, ['ignored.txt', 'tracked.txt', 'added.txt'], NEVER_ABORTED)),
            links=sorted(await gitlinkPaths(runner, workspace, NEVER_ABORTED)), cap=cap,
            untouched=state == repo_state(repo), indexScratch=list(Path(workspace['scratch']).glob('index-*')))]
    finally:
        await ctx.fiber.dispose()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_change_git.mts',
        'Actual original/native subprocess and real Git repository: private index/object-store before/after '
        'snapshots, unstaged/untracked/rename/ignored/literal paths, exact blobs/trees, output cap and unchanged repository index/objects/refs.',
        [Path(__file__).resolve(), ROOT/'dsh/deliverables/change_git.py'], prepare=prepare)
