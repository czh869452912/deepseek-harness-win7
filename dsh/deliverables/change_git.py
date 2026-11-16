"""Private Git snapshots through the injected ordinary subprocess capability."""
import asyncio
import math
import os
import re
import shutil
import tempfile

from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.deliverables.change_numstat import parseNumstat
from dsh.deliverables.change_paths import canonicalPath, isInside, toPosix


class GitRunner:
    def __init__(self, subprocess, executable, limits):
        self.subprocess, self.executable, self.limits = subprocess, executable, limits

    async def run(self, args, options):
        controller = AbortController()
        timeout_ms = self.limits['timeoutMs']
        if type(timeout_ms) not in (int, float) or not math.isfinite(timeout_ms) or timeout_ms < 0 or int(timeout_ms) != timeout_ms:
            raise ValueError('Git timeout must be a non-negative integer')
        expired = [False]
        def expire():
            expired[0] = True
            controller.abort(RuntimeError('Git timeout'))
        timer = asyncio.get_running_loop().call_later(timeout_ms/1000, expire)
        signal = options.get('signal')
        detach = subscribe_abort(signal, lambda *_: controller.abort(signal.reason))
        handle = None
        try:
            stdin = options.get('stdin')
            env = dict(GIT_CONFIG_COUNT='0', GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', LC_ALL='C')
            env.update(options.get('env') or {})
            handle = self.subprocess.spawn(dict(argv=[self.executable]+list(args), cwd=options['cwd'],
                stdio=dict(stdin='ignore' if stdin is None else dict(data=stdin),
                    stdout=dict(maxBytes=options.get('maxBytes', self.limits['outputMaxBytes'])), stderr=dict(maxBytes=16*1024)),
                graceMs=2000, signal=controller.signal, env=env))
            outcome = await handle.done
            if controller.signal.aborted:
                reason = 'timed out after '+str(timeout_ms)+'ms' if expired[0] else 'was aborted'
                raise RuntimeError('git '+' '.join(args)+' '+reason)
            stdout = handle.collected.get('stdout')
            stderr = handle.collected.get('stderr')
            collected = stdout.readFrom(0) if stdout is not None else dict(text='', lossy=False)
            return dict(exitCode=outcome['exitCode'], stdout=collected['text'],
                stderr=stderr.readFrom(0)['text'] if stderr is not None else '', truncated=collected['lossy'])
        except asyncio.CancelledError:
            controller.abort(RuntimeError('Git caller cancelled'))
            if handle is not None:
                await handle.done
            raise
        finally:
            timer.cancel()
            detach()


def ok(result, what):
    if result['exitCode'] != 0:
        raise RuntimeError(what+' failed: '+result['stderr'].strip())
    return result


async def locateGitWorkspace(git, cwd, scratch, signal):
    found = await git.run(['rev-parse', '--show-toplevel', '--absolute-git-dir', '--git-path', 'objects'], dict(cwd=cwd, signal=signal))
    if found['exitCode'] == 128 and re.search('not a git repository', found['stderr'], re.IGNORECASE):
        return None
    lines = ok(found, 'git rev-parse')['stdout'].split('\n')
    root, git_dir, repository_objects = [os.path.abspath(os.path.join(cwd, line)) for line in lines[:3]]
    directory = await canonicalPath(await await_callback_result(scratch()))
    objects = os.path.join(directory, 'objects')
    os.makedirs(objects, exist_ok=True)
    excludes = [toPosix(os.path.relpath(directory, root))] if isInside(root, directory) else []
    return dict(root=root, gitDir=git_dir, scratch=directory, excludes=excludes,
        env=dict(GIT_OBJECT_DIRECTORY=objects, GIT_ALTERNATE_OBJECT_DIRECTORIES=repository_objects))


async def snapshotTree(git, workspace, signal):
    scratch = tempfile.mkdtemp(prefix='index-', dir=workspace['scratch'])
    try:
        index = os.path.join(scratch, 'index')
        try:
            shutil.copyfile(os.path.join(workspace['gitDir'], 'index'), index)
        except FileNotFoundError:
            pass
        env = dict(workspace['env'], GIT_INDEX_FILE=index)
        excludes = workspace['excludes']
        pathspec = ['--', '.']+[':(exclude)'+path for path in excludes] if excludes else []
        added = await git.run(['add', '--all', '--ignore-errors']+pathspec, dict(cwd=workspace['root'], env=env, signal=signal))
        if added['exitCode'] != 1:
            ok(added, 'git add in '+workspace['root'])
        return ok(await git.run(['write-tree'], dict(cwd=workspace['root'], env=env, signal=signal)), 'git write-tree')['stdout'].strip()
    finally:
        shutil.rmtree(scratch)


async def treeBlob(git, workspace, tree, path, signal):
    result = ok(await git.run(['ls-tree', '-z', '-l', tree, '--', path], dict(cwd=workspace['root'],
        env=dict(workspace['env'], GIT_LITERAL_PATHSPECS='1'), signal=signal)), 'git ls-tree')
    match = re.match(r'^\d+ (\S+) ([0-9a-f]+) +(\d+)\t', result['stdout'].split('\0')[0], re.ASCII)
    if match is None or match[1] != 'blob':
        return None
    return dict(oid=match[2], size=int(match[3]))


async def blobText(git, workspace, oid, maxBytes, signal):
    result = ok(await git.run(['cat-file', 'blob', oid], dict(cwd=workspace['root'], env=workspace['env'], maxBytes=maxBytes, signal=signal)), 'git cat-file')
    if result['truncated']:
        raise RuntimeError('blob '+oid+' exceeds '+str(maxBytes)+' bytes')
    return result['stdout']


async def diffTrees(git, workspace, before, after, signal):
    if before == after:
        return []
    result = ok(await git.run(['diff-tree', '-r', '-M', '-z', '--numstat', before, after],
        dict(cwd=workspace['root'], env=workspace['env'], signal=signal)), 'git diff-tree')
    if result['truncated']:
        raise RuntimeError('git diff-tree output exceeded the configured cap')
    return parseNumstat(result['stdout'])


async def gitlinkPaths(git, workspace, signal):
    result = ok(await git.run(['ls-files', '-z', '--stage'], dict(cwd=workspace['root'], env=workspace['env'], signal=signal)), 'git ls-files')
    return {entry[entry.index('\t')+1:] for entry in result['stdout'].split('\0') if entry.startswith('160000 ')}


async def ignoredPaths(git, workspace, paths, signal):
    if not paths:
        return set()
    result = await git.run(['check-ignore', '-z', '--stdin'], dict(cwd=workspace['root'], env=workspace['env'],
        stdin='\0'.join(paths)+'\0', signal=signal))
    if result['exitCode'] == 1:
        return set()
    return {path for path in ok(result, 'git check-ignore')['stdout'].split('\0') if path != ''}
