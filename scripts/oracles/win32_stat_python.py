import argparse
import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys


def public(info):
    if info is None:
        return None
    result = dict(type=info.type, version=info.version)
    if info.size is not None:
        result['size'] = info.size
    return result


def handle_checks(path, provider):
    selected = provider.kernel()
    selected.GetCurrentProcess.restype = wintypes.HANDLE
    selected.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    selected.GetProcessHandleCount.restype = wintypes.BOOL

    def count():
        value = wintypes.DWORD()
        if not selected.GetProcessHandleCount(selected.GetCurrentProcess(), ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.value

    before = count()
    for index in range(256):
        assert provider.node_stat(str(path), os.stat(str(path))).st_size == 8
    assert count() == before
    failures = []
    for boundary in ('GetFileInformationByHandle', 'GetFileInformationByHandleEx'):
        closed = []

        class Fault:
            def __getattr__(self, name):
                if name == boundary:
                    def fail(*arguments):
                        ctypes.set_last_error(5)
                        return 0
                    return fail
                return getattr(selected, name)

            def CloseHandle(self, handle):
                closed.append(handle)
                return selected.CloseHandle(handle)

        provider._KERNEL = Fault()
        try:
            try:
                provider.node_stat(str(path), os.stat(str(path)))
            except OSError as error:
                assert error.winerror == 5
            else:
                raise AssertionError('Native metadata query failure was ignored')
        finally:
            provider._KERNEL = selected
        assert len(closed) == 1 and count() == before
        failures.append(dict(boundary=boundary, winerror=5, closed_handles=len(closed), handle_count=count()))
    return dict(successful_probes=256, initial_handle_count=before, final_handle_count=count(), failures=failures)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    root, destination = arguments.root.resolve(), arguments.destination.resolve()
    sys.path.insert(0, str(root))
    from dsh.cordis.context import Context
    from dsh.fs.fs_local import FsLocalPlugin
    from dsh.fs import win32_stat
    ctx, rows = Context(), []
    try:
        await ctx.plugin(FsLocalPlugin, dict(cwd=str(destination)))
        filesystem = ctx.get('fs')
        for name in ('text.txt', 'empty.txt', '中文.txt', 'fixed-time.txt', 'directory', 'metadata-change.txt', 'missing.txt'):
            target = await filesystem.resolve(name)
            info = await filesystem.stat(target)
            link = await filesystem.lstat(name)
            original = os.stat(str(destination / name)) if info is not None else None
            raw = win32_stat.node_stat(str(destination / name), original) if original is not None else None
            rows.append(dict(name=name, stat=public(info), lstat=public(link), raw=None if raw is None else dict(
                dev=str(raw.st_dev), ino=str(raw.st_ino), size=str(raw.st_size),
                mtimeNs=str(raw.st_mtime_ns), ctimeNs=str(raw.st_ctime_ns))))
    finally:
        await ctx.fiber.dispose()
    handles = handle_checks(destination / 'metadata-change.txt', win32_stat)
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            modules[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version,
            modules=modules, destination=str(destination), rows=rows, handles=handles), stream, indent=2, ensure_ascii=False)
        stream.write('\n')


if __name__ == '__main__':
    asyncio.run(main())
