"""Bounded, cancellable host filesystem directory browsing."""
import asyncio
import bisect
import os
import re
import threading
from functools import partial

from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.host.directory_picker.base import DirectoryPickerService, DirectoryPickerError


def fully_qualified(path):
    return isinstance(path, str) and os.path.isabs(path) and (os.name != 'nt' or re.match(r'^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/]+[^\\/]+)', path) is not None)


class BrowseDirectoryPickerService(DirectoryPickerService):
    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.max_entries = (config or {}).get('maxEntries', 1000)
        if not isinstance(self.max_entries, int) or self.max_entries < 1:
            raise ValueError('maxEntries must be a positive integer')
        self._capability = dict(kind='browse', list=self.list_directory, createDirectory=self.create_directory)

    def capability(self):
        return self._capability

    async def list_directory(self, target_path=None, signal=NEVER_ABORTED):
        signal.throw_if_aborted()
        if target_path is not None and not fully_qualified(target_path):
            raise DirectoryPickerError('directory-unreadable', target_path, 'cannot list "%s": not a fully qualified path' % target_path)
        target = os.path.abspath(target_path if target_path is not None else os.path.expanduser('~'))
        stop = threading.Event()
        def scan():
            window, evicted = [], False
            try:
                with os.scandir(target) as level:
                    for item in level:
                        if stop.is_set():
                            return None
                        if not item.is_symlink() and not item.is_dir(follow_symlinks=False):
                            continue
                        bisect.insort(window, item.name)
                        if len(window) > self.max_entries + 1:
                            window.pop()
                            evicted = True
                entries = []
                for name in window:
                    if stop.is_set():
                        return None
                    path = os.path.join(target, name)
                    if os.path.isdir(path):
                        entries.append(dict(name=name, path=path, hidden=name.startswith('.')))
                crumbs, current = [], target
                while True:
                    parent = os.path.dirname(current)
                    crumbs.insert(0, dict(name=current if parent == current else os.path.basename(current), path=current, hidden=False))
                    if parent == current:
                        break
                    current = parent
                return dict(path=target, home=os.path.expanduser('~'), crumbs=crumbs,
                            entries=entries[:self.max_entries], truncated=evicted or len(entries) > self.max_entries)
            except OSError as error:
                raise DirectoryPickerError('directory-unreadable', target, 'cannot list %s: %s' % (target, error)) from error
        operation = asyncio.get_event_loop().run_in_executor(None, scan)
        abort = asyncio.create_task(signal.wait_aborted())
        try:
            await asyncio.wait([operation, abort], return_when=asyncio.FIRST_COMPLETED)
            signal.throw_if_aborted()
            return await operation
        finally:
            stop.set()
            abort.cancel()
            await asyncio.gather(abort, return_exceptions=True)
            # A filesystem call cannot be interrupted on Win7; the worker closes
            # its scan handle when that call returns, without retaining the caller.
            operation.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)

    async def create_directory(self, parent_path, name):
        if not fully_qualified(parent_path):
            raise DirectoryPickerError('directory-create-failed', parent_path, 'cannot create under "%s": not a fully qualified parent path' % parent_path)
        target = os.path.join(os.path.abspath(parent_path), name)
        if not name.strip() or name in ('.', '..') or '/' in name or chr(92) in name:
            raise DirectoryPickerError('directory-create-failed', target, '"%s" is not a single path segment' % name)
        try:
            await asyncio.get_event_loop().run_in_executor(None, partial(os.mkdir, target))
            return target
        except FileExistsError as error:
            raise DirectoryPickerError('directory-exists', target, '%s already exists' % target) from error
        except OSError as error:
            raise DirectoryPickerError('directory-create-failed', target, 'cannot create %s: %s' % (target, error)) from error


class BrowseDirectoryPickerPlugin(Plugin):
    id = 'host-directory-picker-browse'
    name = '@deepseek-ai/dsh-host-directory-picker-browse'

    def apply(self, ctx):
        BrowseDirectoryPickerService(ctx, self.config)
