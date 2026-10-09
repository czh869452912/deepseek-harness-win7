"""Use only the selected runtime and its default native search input."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace


async def observe(root, workspace):
    from dsh.cordis.context import Context
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.tools import ToolsPlugin, ToolExecutionInput
    from dsh.fs.tool_fs_search import ToolFsSearchPlugin
    from dsh.fs.tool_fs_search.search_core import resolve_rg_path
    from dsh.subprocess import LocalSubprocessRuntime

    workspace.mkdir()
    (workspace / '中文.txt').write_bytes('hello 中文\n'.encode('utf-8'))
    ctx = Context()
    try:
        SystemPrompt(ctx)
        await ctx.plugin(ToolsPlugin)
        LocalSubprocessRuntime(ctx)
        fiber = await ctx.plugin(ToolFsSearchPlugin, {'sampleOverCapGlobResults': False})
        agent = SimpleNamespace(ctx=fiber.ctx,
            session=SimpleNamespace(header=SimpleNamespace(id='isolated-native-search', cwd=str(workspace))))
        public = []
        for name, arguments in (('glob', {'pattern': '*.txt'}), ('grep', {'pattern': '中文'})):
            result = await ctx.get('tools').execute(ToolExecutionInput(
                'native-' + name, name, arguments, agent=agent, signal=asyncio.Event()))
            public.append(dict(name=name, value=result.value, content=result.content,
                isError=result.is_error, error=result.error, metaPresent=result._meta_present,
                meta=result.meta, concludesTurn=result.concludes_turn, additionalContexts=result.additional_contexts))
        binary = Path(await resolve_rg_path()).resolve()
        version = subprocess.run([str(binary), '--version'], capture_output=True, timeout=15)
        modules = {}
        for name, module in tuple(sys.modules.items()):
            filename = getattr(module, '__file__', None)
            if filename and (name == 'dsh' or name.startswith('dsh.')):
                path = Path(filename).resolve()
                relative = path.relative_to(root).as_posix()
                modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules,
            workspace=str(workspace), binary=str(binary), binarySha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            path=os.environ.get('PATH'), explicitOverridePresent='DSH_RG_PATH' in os.environ,
            hostNodeFound=shutil.which('node') is not None,
            version=dict(exitCode=version.returncode, stdout=version.stdout.decode('utf-8'), stderr=version.stderr.decode('utf-8')),
            public=public)
    finally:
        await ctx.fiber.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    if args.output.exists() or args.workspace.exists():
        raise ValueError('Fresh native search observation required')
    value = asyncio.run(observe(root, args.workspace.resolve()))
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
