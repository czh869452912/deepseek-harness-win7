"""Portable change-only root watching with an awaited initial inventory."""
import asyncio
import os
import stat
import re
import time


_EDITOR_TEMP = re.compile(r'\..*\.(sw[px])$|~$|\.subl.*\.tmp')


def atomic_delay(config):
    value = config.get('atomic', not config.get('usePolling', False))
    return (100 if value is True else value) / 1000.0 if value else 0


def write_finish(config):
    value = config.get('awaitWriteFinish')
    if value is True:
        return dict(stabilityThreshold=2000, pollInterval=100)
    if isinstance(value, dict):
        return dict(dict(stabilityThreshold=2000, pollInterval=100), **value)
    return None


def observe_changes(hmr, previous, current, now):
    """Normalize unlink/add pairs and defer incomplete add/change writes."""
    atomic, finish = atomic_delay(hmr.config), write_finish(hmr.config)
    unlinks, writes = hmr._root_unlinks, hmr._root_writes
    # Each original unlink timer flushes the shared pending-unlink map.
    if any(now >= deadline for deadline in hmr._root_unlink_deadlines):
        unlinks.clear()
        hmr._root_unlink_deadlines[:] = [deadline for deadline in hmr._root_unlink_deadlines if deadline > now]
    for path, emitted in list(hmr._root_emitted.items()):
        if now-emitted >= .05:
            del hmr._root_emitted[path]
    for path in previous:
        if path not in current:
            pending = writes.pop(path, None)
            if atomic and (pending is None or pending['kind'] != 'add'):
                unlinks[path] = now
                hmr._root_unlink_deadlines.append(now+atomic)
    for path, identity in current.items():
        kind = None
        if path not in previous:
            kind = 'change' if path in unlinks else 'add'
            unlinks.pop(path, None)
        elif identity != previous[path]:
            kind = 'change'
        if kind is not None:
            if finish:
                pending = writes.get(path)
                if pending is None:
                    writes[path] = dict(kind=kind, changed=now, check=now+finish['pollInterval']/1000.0)
                else:
                    pending['changed'] = now
            elif kind == 'change':
                # Chokidar suppresses repeated change emissions for 50ms.
                if now-hmr._root_emitted.get(path, float('-inf')) >= .05:
                    hmr._root_emitted[path] = now
                    hmr._module_changed(os.path.relpath(path, hmr.watch_base_dir))
        pending = writes.get(path)
        if pending is not None and now >= pending['check']:
            pending['check'] = now+finish['pollInterval']/1000.0
            if now-pending['changed'] >= finish['stabilityThreshold']/1000.0:
                del writes[path]
                if pending['kind'] == 'change':
                    hmr._module_changed(os.path.relpath(path, hmr.watch_base_dir))


async def scan(hmr, initial=False):
    previous, current = hmr._root_mtimes, {}
    follow = hmr.config.get('followSymlinks', True)
    limit = hmr.config.get('depth')
    atomic = atomic_delay(hmr.config)
    async def visit(path, depth, ancestors, entry=None):
        await asyncio.sleep(0)
        if hmr.is_ignored(path, hmr.watch_base_dir):
            return
        if atomic and _EDITOR_TEMP.search(path):
            return
        try:
            if entry is None:
                info = os.stat(path) if follow else os.lstat(path)
            else:
                info = entry.stat(follow_symlinks=follow)
            if not follow and (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400):
                return
            if stat.S_ISDIR(info.st_mode):
                canonical = os.path.normcase(os.path.realpath(path))
                if canonical in ancestors:
                    return
                if limit is not None and depth > limit:
                    return
                with os.scandir(path) as children:
                    entries = list(children)
                descendants = ancestors | {canonical}
                for child in entries:
                    await visit(child.path, depth+1, descendants, child)
            elif stat.S_ISREG(info.st_mode):
                current[path] = (info.st_mtime, info.st_size)
        except OSError as error:
            if isinstance(error, (FileNotFoundError, NotADirectoryError)) or getattr(error, 'winerror', None) == 123:
                return
            if not (hmr.config.get('ignorePermissionErrors') and isinstance(error, PermissionError)):
                raise
    for root in hmr.root:
        await visit(os.path.abspath(os.path.join(hmr.watch_base_dir, root)), 0, set())
    hmr._root_mtimes = current
    hmr._initial_scanned = True
    if not initial:
        observe_changes(hmr, previous, current, time.monotonic())
