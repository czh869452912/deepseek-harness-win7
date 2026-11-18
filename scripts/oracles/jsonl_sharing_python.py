import argparse
import asyncio
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-observer', action='store_true')
    parser.add_argument('--format-version', type=int, choices=(3, 4), default=3)
    parser.add_argument('--fixtures-from', type=Path)
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    workspace = output.with_suffix('.workspace')
    expected_rows = None
    if options.fixtures_from:
        # Revisions identify physical files. A second reader must use the
        # original files, without opening a writer or recreating their bytes.
        if options.source_observer:
            raise ValueError('Fixture reuse cannot produce new Source observations')
        receipt = options.fixtures_from.resolve()
        expected_rows = json.loads(receipt.read_text(encoding='utf-8'))['rows']
        if tuple(row['name'] for row in expected_rows) != ('none/delete', 'none/write', 'zstd/delete', 'zstd/write'):
            raise ValueError('Complete ordered JSONL sharing fixtures required')
        workspace = receipt.with_suffix('.workspace')
        if not all((workspace / name.replace('/', '-')).is_dir() for name in ('none/delete', 'none/write', 'zstd/delete', 'zstd/write')):
            raise ValueError('Original physical JSONL sharing fixtures missing')
    if output.exists() or (not options.fixtures_from and workspace.exists()):
        raise ValueError('Fresh JSONL sharing outputs required')
    if os.name != 'nt' or sys.version_info[:3] != (3, 8, 10):
        raise ValueError('Actual Windows Python3.8.10 required')
    sys.path.insert(0, str(root))
    from dsh.cordis.context import Context
    from dsh.core.session.current_session import CurrentSessionPlugin as SessionPlugin
    if options.format_version == 4:
        from dsh.core.runtime_v4 import SessionV4Plugin as SessionPlugin
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin as JsonlSessionPersistencePlugin
    from dsh.session.file_revision import _windows_api
    from dsh.session.file_io import open_shared_read
    if not options.fixtures_from:
        workspace.mkdir()
    rows = []
    api, _, HandleInformation, _ = _windows_api()
    for compression in ('none', 'zstd'):
        for access in ('delete', 'write'):
            name = compression + '/' + access
            ctx = Context()
            await ctx.plugin(SessionPlugin)
            await ctx.plugin(JsonlSessionPersistencePlugin, dict(root=str(workspace / (compression + '-' + access)), compression=compression))
            provider = ctx.get('sessionPersistence')
            meta = dict(id='sharing-session',version=options.format_version,createdAt=1,isSeeded=False)
            if not options.fixtures_from:
                writer = await provider.create(meta)
                await writer.append([dict(type='session/end-seed', seq=0, time=1, data={})])
            path = provider.locate(meta)
            absolute = '\\\\?\\' + os.path.abspath(path)
            handle = api.CreateFileW(absolute, 0x80010000 if access == 'delete' else 0xC0000000, 7, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                listed = await provider.list()
                reader = await provider.open(meta['id'], 'read')
                try:
                    inspected = dict(await reader.read(), header=reader.header, inheritedEventCount=reader.inheritedEventCount)
                finally:
                    await reader.close()
                # readRaw is retired: retain physical bytes as diagnostics,
                # alongside the complete current public list/read results.
                with open_shared_read(path) as stream:
                    raw = dict(filename=os.path.basename(path),content=base64.b64encode(stream.read()).decode('ascii'))
                observed = dict(listed=listed, inspected=inspected, raw=raw)
                rows.append(dict(name=name, observed=observed))
                if options.source_observer:
                    repository = Path(__file__).resolve().parents[2]
                    source_output = output.with_suffix('.' + compression + '-' + access + '.source.json')
                    environment = dict(os.environ, DSH_JSONL_SHARING_ROOT=provider.root,
                        DSH_JSONL_SHARING_COMPRESSION=compression, DSH_JSONL_SHARING_NAME=name,
                        DSH_JSONL_SHARING_FILE=path,
                        DSH_JSONL_SHARING_SOURCE_OUTPUT=str(source_output))
                    with output.with_suffix('.' + compression + '-' + access + '.source.log').open('x', encoding='utf-8') as stream:
                        completed = subprocess.run(['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                            'run', '--config', 'scripts/oracles/vitest.rc022-jsonl-sharing-probe.config.mts' if options.format_version == 4 else 'scripts/oracles/vitest.jsonl-sharing-probe.config.mts'], cwd=str(repository),
                            env=environment, stdout=stream, stderr=subprocess.STDOUT, timeout=60)
                    if completed.returncode:
                        raise RuntimeError('Actual original JSONL sharing observer failed: ' + name)
                if not api.GetFileInformationByHandle(handle, ctypes.byref(HandleInformation())):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                closed = api.CloseHandle(handle)
                await ctx.fiber.dispose()
                if not closed:
                    raise ctypes.WinError(ctypes.get_last_error())
    if expected_rows is not None and rows != expected_rows:
        raise ValueError('Reused JSONL sharing fixtures or complete observations changed')
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), python=sys.version, executable=sys.executable, modules=modules, rows=rows), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    asyncio.run(main())
