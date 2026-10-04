import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading


EXPECTED = [
    dict(mode=mode, blocked=True, released=True, published=True, content='owned')
    for mode in ('directory', 'file')
] + [dict(mode='permanent-' + mode, timedOut=True, originalManifest=True,
          completeJournal=True, recovered=True)
     for mode in ('directory', 'file')]


def validate(report):
    if (not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python', 'platform'}
            or report['python'] != '3.8.10' or report['platform'] != 'win32'
            or not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/boot/python_directory_mutation.py').resolve()):
        raise ValueError('Owned Python directory runtime provenance differs')
    canonical = lambda value: json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))
    if canonical(report['observations']) != canonical(EXPECTED):
        raise ValueError('Owned Python directory publication, timeout or complete journal differs')


def observe(root):
    sys.path.insert(0, str(root))
    from dsh.boot import python_directory_mutation as mutation, python_plugins as store
    kernel = mutation._windows_api()
    observations = []
    with tempfile.TemporaryDirectory(prefix='dsh-directory-probe-') as temporary:
        workspace = Path(temporary)
        for mode in ('directory', 'file'):
            source = workspace / mode
            source.mkdir()
            (source / 'data').write_text('owned', encoding='utf-8')
            held = source if mode == 'directory' else source / 'data'
            handle = kernel.CreateFileW(str(held), 0x80000000, 3, None, 3, 0x02000000, None)
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            blocked = False
            try:
                os.replace(str(source), str(source) + '-blocked')
            except PermissionError:
                blocked = True
            released = []

            def release(active=handle):
                released.append(bool(kernel.CloseHandle(active)))

            timer = threading.Timer(0.08, release)
            timer.start()
            target = workspace / (mode + '-published')
            try:
                mutation.replace_directory(str(source), str(target))
            finally:
                timer.join()
            observations.append(dict(mode=mode, blocked=blocked, released=released == [True],
                published=target.is_dir() and not source.exists(), content=(target / 'data').read_text(encoding='utf-8')))
        for mode in ('directory', 'file'):
            directory = workspace / ('permanent-' + mode)
            directory.mkdir()
            before = store.json_bytes(dict(name='probe', dependencies={}))
            (directory / 'package.json').write_bytes(before)
            token = '0' * 32
            stage = directory / store.STAGING / token
            stage.mkdir(parents=True)
            (stage / 'data').write_text('owned', encoding='utf-8')
            held = stage if mode == 'directory' else stage / 'data'
            handle = kernel.CreateFileW(str(held), 0x80000000, 3, None, 3, 0x02000000, None)
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            timed_out = False
            try:
                try:
                    store.transact(str(directory), before, dict(name='probe', dependencies={'probe': 'managed'}), 'probe', token, 'add')
                except PermissionError as error:
                    timed_out = error.winerror == 32
                journal = json.loads((directory / store.JOURNAL).read_text(encoding='utf-8'))
                complete = store.file_hashes(str(stage)) == journal['files']
                original = (directory / 'package.json').read_bytes() == before
            finally:
                if not kernel.CloseHandle(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            store.recover(str(directory))
            observations.append(dict(mode='permanent-' + mode, timedOut=timed_out,
                originalManifest=original, completeJournal=complete,
                recovered=not (directory / store.JOURNAL).exists() and not stage.exists()))
    return dict(observations=observations, root=str(root), module=str(Path(mutation.__file__).resolve()),
                python='.'.join(str(value) for value in sys.version_info[:3]), platform=sys.platform)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = observe(args.root.resolve())
    validate(report)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
