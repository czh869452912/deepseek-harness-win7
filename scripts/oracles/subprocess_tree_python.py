import argparse
import ctypes
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
NAMES = ('direct', 'dispose', 'abort', 'terminate')


def observe(product_root, python, source=False, environment=None):
    if sys.platform != 'win32':
        raise RuntimeError('This physical tree observer requires Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    rows = []
    for trigger in NAMES:
        with tempfile.TemporaryDirectory(prefix='dsh physical tree \u4e2d\u6587 ') as directory:
            workspace = Path(directory)
            peer = ROOT / 'scripts/oracles/subprocess_tree_peer.py'
            if source:
                node = shutil.which('node')
                if node is None:
                    raise RuntimeError('Source tree observer requires Node')
                command = [node, '--import', (ROOT / 'scripts/oracles/subprocess_source_host_loader.mjs').as_uri(),
                    str(ROOT / 'scripts/oracles/subprocess_host_exit_source.ts'), str(workspace), trigger, python, str(peer)]
            else:
                command = [python, '-I', str(ROOT / 'scripts/oracles/subprocess_host_exit_python.py'),
                    str(workspace), trigger, '--root', str(product_root), '--peer', str(peer)]
            host = subprocess.Popen(command, cwd=str(workspace), env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            handles = []
            try:
                deadline = time.monotonic() + 10
                while not (workspace / 'tree.json').is_file():
                    if time.monotonic() >= deadline or host.poll() is not None:
                        if host.poll() is not None:
                            stdout, stderr = host.communicate(timeout=2)
                            raise RuntimeError('Managed tree did not publish readiness: ' + stderr.decode('utf-8', 'replace'))
                        raise RuntimeError('Managed tree did not publish readiness before deadline')
                    time.sleep(0.01)
                state = json.loads((workspace / 'tree.json').read_text(encoding='utf-8'))
                if (set(state) != {'root', 'descendant', 'cwd'} or state['cwd'] != str(workspace)
                        or any(type(state[name]) is not int or state[name] <= 0 for name in ('root', 'descendant'))
                        or state['root'] == state['descendant']):
                    raise RuntimeError('Managed tree published invalid physical ownership')
                for name in ('root', 'descendant'):
                    handle = kernel.OpenProcess(0x101001, False, state[name])
                    if not handle:
                        raise ctypes.WinError(ctypes.get_last_error())
                    handles.append((name, handle))
                before = {name: kernel.WaitForSingleObject(handle, 0) == 258 for name, handle in handles}
                (workspace / 'proceed').write_text('proceed', encoding='utf-8')
                stdout, stderr = host.communicate(timeout=10)
                for name, handle in handles:
                    kernel.WaitForSingleObject(handle, 5000)
                after = {name: kernel.WaitForSingleObject(handle, 0) == 258 for name, handle in handles}
                row = {'name': trigger, 'observed': {'exitCode': host.returncode, 'before': before,
                    'after': after, 'stdout': stdout.decode('utf-8', 'strict'), 'stderr': stderr.decode('utf-8', 'strict')},
                    'physical': {'host': host.pid, **state}}
                if not source:
                    row['product'] = json.loads((workspace / 'product.json').read_text(encoding='utf-8'))
                rows.append(row)
            finally:
                for name, handle in reversed(handles):
                    if kernel.WaitForSingleObject(handle, 0) == 258:
                        kernel.TerminateProcess(handle, 99)
                        kernel.WaitForSingleObject(handle, 5000)
                    kernel.CloseHandle(handle)
                if host.poll() is None:
                    host.kill()
                    host.communicate(timeout=5)
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--source', action='store_true')
    arguments = parser.parse_args()
    arguments.output.write_text(json.dumps(observe(arguments.root.resolve(), arguments.python, arguments.source),
        ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
