"""Portable change-only root watching with an awaited initial inventory."""
import asyncio
import os
import stat


async def scan(hmr, initial=False):
    previous, current = hmr._root_mtimes, {}
    follow = hmr.config.get('followSymlinks', True)
    limit = hmr.config.get('depth')
    async def visit(path, depth, ancestors):
        await asyncio.sleep(0)
        if hmr.is_ignored(path, hmr.watch_base_dir):
            return
        try:
            info = os.stat(path) if follow else os.lstat(path)
            if not follow and (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400):
                return
            if stat.S_ISDIR(info.st_mode):
                canonical = os.path.normcase(os.path.realpath(path))
                if canonical in ancestors:
                    return
                if limit is not None and depth > limit:
                    return
                for name in os.listdir(path):
                    await visit(os.path.join(path, name), depth+1,
                                ancestors | {canonical})
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
        for path, identity in current.items():
            if path in previous and identity != previous[path]:
                hmr._module_changed(os.path.relpath(path, hmr.watch_base_dir))
