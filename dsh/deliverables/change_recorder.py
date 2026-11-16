"""Per-session turn snapshots, pre-mutation captures and lazy comparisons."""
import asyncio
import functools
import os
import shutil
import stat
import tempfile

from dsh.cordis.awaiting import await_callback_result
from dsh.core.abort import AbortController, abort_reason_error
from dsh.core.cancellation import subscribe_abort
from dsh.deliverables.change_capture import captureFile, sameCapture
from dsh.deliverables.change_compare import compareText
from dsh.deliverables.change_git import (blobText, diffTrees, gitlinkPaths, ignoredPaths,
    locateGitWorkspace, snapshotTree, treeBlob)
from dsh.deliverables.change_paths import (canonicalPath, compareDisplay, displayPathOf,
    durablePathOf, isInside, isTemporaryPath, temporaryRoots, toPosix)


_OVERSIZED = object()


def freshState(turn):
    return dict(turn=turn, baseline=None, captures={}, lastToolResultSeq=-1,
                attemptedAfterSeq=-1, recordedAfterSeq=-1)


def changedFile(paths, root, absolute, counts):
    file = dict(path=durablePathOf(absolute, paths['cwd']),
                display=displayPathOf(absolute, paths['cwd'], root, paths['home']),
                added=counts['added'], deleted=counts['deleted'])
    for flag in ('binary', 'oversized'):
        if counts.get(flag):
            file[flag] = True
    return file


def _remove_scratch(directory):
    # Git writes read-only loose objects on Windows. Never change attributes on
    # shared hardlinks, links, or files outside this recorder's owned directory.
    root = os.path.realpath(directory)
    def readonly(function, path, error):
        info = os.lstat(path)
        if (function is not os.unlink or not isinstance(error[1], PermissionError)
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not isInside(root, os.path.realpath(path))
                or 'objects' not in os.path.relpath(path, root).split(os.sep)
                or not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_READONLY):
            raise error[1]
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.unlink(path)
    shutil.rmtree(directory, onerror=readonly)


class TurnRecorder:
    def __init__(self, session, cwd, env):
        self.session, self.cwd, self.env = session, cwd, env
        self.state = freshState(0)
        self.paths = self.repository = self.scratch = None
        self.records = {}
        self.lifetime = AbortController()
        self.chain = asyncio.get_running_loop().create_future()
        self.chain.set_result(None)

    def enqueue(self, task):
        previous = self.chain
        async def run():
            await asyncio.shield(previous)
            if self.lifetime.signal.aborted:
                return
            try:
                await task(self.lifetime.signal)
            except Exception as error:
                if not self.lifetime.signal.aborted:
                    self.env['warn']('workspace-changes: '+str(error))
        self.chain = asyncio.create_task(run())
        return asyncio.shield(self.chain)

    def start(self, turn):
        state = self.state = freshState(turn)
        async def start(signal):
            try:
                if self.paths is None:
                    # realpath must reject a missing original cwd, as in Node.
                    os.stat(self.cwd)
                    self.paths = dict(cwd=os.path.realpath(self.cwd),
                        home=await canonicalPath(os.path.expanduser('~')),
                        temporaryRoots=await temporaryRoots())
                repository = await self.locate(self.paths['cwd'], signal)
                if repository is not None:
                    tree = await snapshotTree(repository['git'], repository['workspace'], signal)
                    state['baseline'] = dict(repository, tree=tree)
            except Exception:
                state['baseline'] = 'failed'
                raise
        self.enqueue(start)

    def capture(self, path):
        state = self.state
        async def capture(signal):
            if self.paths is None:
                return
            absolute = await canonicalPath(path)
            if absolute in state['captures']:
                return
            value = await captureFile(absolute, os.path.join(await self.scratchDir(), 'captures'), self.env['maxFileBytes'])
            if value is not None:
                state['captures'][absolute] = value
        self.enqueue(capture)

    def observe(self, event):
        if event['data']['turn'] == self.state['turn']:
            self.state['lastToolResultSeq'] = event['seq']

    async def stopping(self, turn):
        state = self.state
        if turn == state['turn']:
            await self.enqueue(lambda signal: self.record(state, signal))

    def end(self, turn):
        state = self.state
        if turn == state['turn'] and state['attemptedAfterSeq'] < state['lastToolResultSeq']:
            self.enqueue(lambda signal: self.record(state, signal))

    async def settled(self):
        await asyncio.shield(self.chain)

    def summary(self, seq):
        record = self.records.get(seq)
        return None if record is None else record['summary']

    async def diff(self, seq, index, signal):
        record = self.records.get(seq)
        if record is None or type(index) is not int or index < 0 or index >= len(record['sources']):
            return None
        file, sources = record['summary']['files'][index], record['sources'][index]
        result = dict(path=file['path'], display=file['display'])
        if 'refusal' in sources:
            return dict(result, kind=sources['refusal'])
        combined = AbortController()
        detach = [subscribe_abort(part, lambda *_, part=part: combined.abort(part.reason))
                  for part in (signal, self.lifetime.signal) if part is not None]
        try:
            before, after = await asyncio.gather(self.readSide(sources['before'], combined.signal),
                                                self.readSide(sources['after'], combined.signal))
            if before is _OVERSIZED or after is _OVERSIZED:
                return dict(result, kind='oversized')
            compared = compareText(before, after, self.env['diffTimeoutMs'])
            return dict(result, kind='text', before=before is not None, after=after is not None,
                        hunks=compared['hunks'], coarse=compared['coarse'])
        except Exception:
            if self.lifetime.signal.aborted:
                return None
            raise
        finally:
            for remove in detach:
                remove()

    async def dispose(self):
        self.lifetime.abort()
        self.records.clear()
        await self.settled()
        if self.scratch is not None:
            await asyncio.get_running_loop().run_in_executor(None, _remove_scratch, self.scratch)
            self.scratch = None

    async def scratchDir(self):
        if self.scratch is None:
            self.scratch = tempfile.mkdtemp(prefix='dsh-workspace-changes-', dir=self.env['tempRoot'])
        return self.scratch

    async def locate(self, cwd, signal):
        if self.repository is not None:
            return self.repository
        git = await await_callback_result(self.env['git'])
        if git is None:
            return None
        workspace = await locateGitWorkspace(git, cwd, self.scratchDir, signal)
        if workspace is not None:
            self.repository = dict(git=git, workspace=workspace)
        return self.repository

    async def readSide(self, source, signal):
        if source['kind'] == 'absent':
            return None
        if source['kind'] == 'file':
            def read():
                with open(source['file'], encoding='utf-8', errors='replace', newline='') as stream:
                    return stream.read()
            pending = asyncio.get_running_loop().run_in_executor(None, read)
            try:
                text = await asyncio.shield(pending)
            except asyncio.CancelledError:
                await asyncio.shield(pending)
                raise
            if signal.aborted:
                raise abort_reason_error(signal)
            return text
        git, workspace = source['repository']['git'], source['repository']['workspace']
        blob = await treeBlob(git, workspace, source['tree'], source['path'], signal)
        if blob is None:
            return None
        if blob['size'] > self.env['maxFileBytes']:
            return _OVERSIZED
        return await blobText(git, workspace, blob['oid'], self.env['maxFileBytes'], signal)

    async def record(self, state, signal):
        paths, baseline = self.paths, state['baseline']
        if paths is None or baseline == 'failed' or state['lastToolResultSeq'] < 0:
            return
        state['attemptedAfterSeq'] = state['lastToolResultSeq']
        root = baseline['workspace']['root'] if baseline is not None else paths['cwd']
        listed, snapshot = {}, None
        if baseline is not None:
            git, workspace = baseline['git'], baseline['workspace']
            after = await snapshotTree(git, workspace, signal)
            snapshot = dict(before=baseline['tree'], after=after)
            repository = dict(git=git, workspace=workspace)
            for entry in await diffTrees(git, workspace, baseline['tree'], after, signal):
                absolute = os.path.abspath(os.path.join(root, entry['path']))
                sources = dict(refusal='binary') if entry['binary'] else dict(
                    before=dict(kind='snapshot', repository=repository, tree=baseline['tree'], path=entry.get('oldPath', entry['path'])),
                    after=dict(kind='snapshot', repository=repository, tree=after, path=entry['path']))
                listed[absolute] = dict(file=changedFile(paths, root, absolute, entry), sources=sources)
        captured = [path for path in state['captures'] if path not in listed]
        def relative(path):
            return toPosix(os.path.relpath(path, root))
        in_workspace = [path for path in captured if isInside(root, path)]
        if baseline is not None and in_workspace:
            links = await gitlinkPaths(git, workspace, signal)
            in_workspace = [path for path in in_workspace if not any(isInside(os.path.abspath(os.path.join(root, link)), path) for link in links)]
        uncovered = (set(map(relative, in_workspace)) if baseline is None else
                     await ignoredPaths(git, workspace, list(map(relative, in_workspace)), signal))
        for absolute in captured:
            include = relative(absolute) in uncovered if isInside(root, absolute) else not isTemporaryPath(absolute, paths['temporaryRoots'])
            if not include:
                continue
            before = state['captures'][absolute]
            after = await captureFile(absolute, os.path.join(await self.scratchDir(), 'captures'), self.env['maxFileBytes'])
            if after is not None and not sameCapture(before, after):
                listed[absolute] = await self.compared(paths, root, absolute, before, after)
        sorted_files = sorted(listed.values(), key=functools.cmp_to_key(lambda a, b: compareDisplay(a['file'], b['file'])))
        if not sorted_files and state['recordedAfterSeq'] < 0:
            return
        event = self.session.append('workspace/changes', dict(turn=state['turn']))
        seq = event['seq'] if isinstance(event, dict) else event.seq
        kept = sorted_files[:self.env['maxFiles']]
        summary = dict(turn=state['turn'], cwd=self.cwd, files=[entry['file'] for entry in kept],
            total=len(sorted_files), added=sum(entry['file']['added'] for entry in sorted_files),
            deleted=sum(entry['file']['deleted'] for entry in sorted_files))
        if snapshot is not None:
            summary['snapshot'] = snapshot
        self.records[seq] = dict(summary=summary, sources=[entry['sources'] for entry in kept])
        state['recordedAfterSeq'] = seq

    async def compared(self, paths, root, absolute, before, after):
        refusal = ('oversized' if any(side['kind'] == 'oversized' for side in (before, after)) else
                   'binary' if any(side.get('binary') for side in (before, after)) else None)
        if refusal:
            counts = dict(added=0, deleted=0, **{refusal: True})
            sources = dict(refusal=refusal)
        else:
            async def text(side):
                return await self.readSide(side, self.lifetime.signal)
            counts = compareText(await text(before), await text(after), self.env['diffTimeoutMs'])
            sources = dict(before=before, after=after)
        return dict(file=changedFile(paths, root, absolute, counts), sources=sources)
