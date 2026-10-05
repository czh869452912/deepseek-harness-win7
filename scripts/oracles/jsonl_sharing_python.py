import argparse
import asyncio
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
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    workspace = output.with_suffix('.workspace')
    if output.exists() or workspace.exists():
        raise ValueError('Fresh JSONL sharing outputs required')
    if os.name != 'nt' or sys.version_info[:3] != (3, 8, 10):
        raise ValueError('Actual Windows Python3.8.10 required')
    sys.path.insert(0, str(root))
    from dsh.cordis.context import Context
    from dsh.core.session import SessionPlugin, SessionHeader
    from dsh.session.persistence_jsonl_canonical import JsonlSessionPersistencePlugin
    from dsh.session.file_revision import _windows_api
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
            meta = SessionHeader('sharing-session', created_at=1)
            await provider.create(meta)
            await provider.append(meta.id, [dict(type='session/end-seed', seq=0, time=1, data={})])
            path = provider.store.locate(meta.to_dict())
            absolute = '\\\\?\\' + os.path.abspath(path)
            handle = api.CreateFileW(absolute, 0x80010000 if access == 'delete' else 0xC0000000, 7, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                listed = [value.to_dict() for value in await provider.list()]
                inspected = await provider.inspect(meta.id)
                raw = await provider.read_raw(meta.id)
                raw = dict(raw, meta=raw['meta'].to_dict())
                observed = dict(listed=listed, inspected=dict(meta=inspected.meta.to_dict(), events=inspected.events), raw=raw)
                rows.append(dict(name=name, observed=observed))
                if options.source_observer:
                    repository = Path(__file__).resolve().parents[2]
                    source_output = output.with_suffix('.' + compression + '-' + access + '.source.json')
                    environment = dict(os.environ, DSH_JSONL_SHARING_ROOT=provider.root,
                        DSH_JSONL_SHARING_COMPRESSION=compression, DSH_JSONL_SHARING_NAME=name,
                        DSH_JSONL_SHARING_SOURCE_OUTPUT=str(source_output))
                    with output.with_suffix('.' + compression + '-' + access + '.source.log').open('x', encoding='utf-8') as stream:
                        completed = subprocess.run(['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                            'run', '--config', 'scripts/oracles/vitest.jsonl-sharing-probe.config.mts'], cwd=str(repository),
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
