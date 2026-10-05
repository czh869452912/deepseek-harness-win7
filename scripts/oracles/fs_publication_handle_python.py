import asyncio
import ctypes
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.fs.fs_local import FsService, _to_namespaced_path


async def observe():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                          ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    open_file.restype = ctypes.c_void_p
    close = kernel.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int
    rows = []
    with tempfile.TemporaryDirectory(prefix='native-fs-publication-') as directory:
        root = Path(directory)
        for sharing in [3, 7]:
            target = root / ('target-' + str(sharing))
            target.write_text('old', encoding='utf-8')
            fs = FsService(cwd=str(root))
            handles = []

            def hold(paths):
                handle = open_file(_to_namespaced_path(str(target)), 0x80000000, sharing, None, 3, 0x80, None)
                if handle in (None, ctypes.c_void_p(-1).value):
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(handle)

            fs.internals.inspectTemp = hold
            error = None
            try:
                await fs.writeText(await fs.resolve(str(target)), 'new')
            except OSError as failure:
                error = dict(win32Code=failure.winerror, errno=failure.errno, message=str(failure))
            finally:
                for handle in handles:
                    if not close(handle):
                        raise ctypes.WinError(ctypes.get_last_error())
            rows.append(dict(sharing=sharing, error=error, content=target.read_text(encoding='utf-8'),
                             staging=sorted(path.name for path in root.iterdir() if path.name.endswith('.tmpdir'))))
            fs.internals.inspectTemp = None
            await fs.writeText(await fs.resolve(str(target)), 'released')
            rows.append(dict(sharing=sharing, released=True, content=target.read_text(encoding='utf-8'),
                             staging=sorted(path.name for path in root.iterdir() if path.name.endswith('.tmpdir'))))
    return rows


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()), indent=2) + '\n', encoding='utf-8')
