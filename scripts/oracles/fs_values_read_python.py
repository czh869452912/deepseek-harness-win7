import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
selected_root = arguments.root.resolve()
work = arguments.output.parent
sys.path.insert(0, str(selected_root))
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.fs.fs_local import FsError, FsInfo, FsTarget
from dsh.fs.tool_fs import ToolFsPlugin


async def observe(fixture):
    ctx, trace = Context(), []
    signal = AbortController().signal

    class Provider:
        sandboxMode = None

        def fail_if_armed(self, kind):
            if fixture.get('reject') == kind:
                raise FsError('provider ' + kind + ' failed', 'FS_IO_ERROR')

        async def resolve(self, path, options):
            row = dict(kind='resolve', path=path, signalSame=options.get('signal') is signal)
            if 'cwd' in options:
                row['cwd'] = options['cwd']
            trace.append(row)
            return FsTarget('key:' + path, '/abs/' + path)

        async def stat(self, target, live_signal):
            trace.append(dict(kind='stat', signalSame=live_signal is signal))
            self.fail_if_armed('stat')
            return None if fixture.get('missing') else FsInfo('v1', fixture.get('type', 'file'), fixture.get('size'))

        async def readText(self, target, live_signal):
            trace.append(dict(kind='readText', signalSame=live_signal is signal))
            self.fail_if_armed('readText')
            return ''.join(fixture['chunks'])

        async def streamText(self, target, live_signal):
            trace.append(dict(kind='streamText', signalSame=live_signal is signal))
            self.fail_if_armed('streamText')

            async def chunks():
                for chunk in fixture['chunks']:
                    trace.append(dict(kind='chunk', text=chunk))
                    yield chunk
                    if fixture.get('reject') == 'chunk':
                        raise FsError('provider chunk failed', 'FS_IO_ERROR')
            return chunks()

    class MountProvider(Plugin):
        def apply(self, carrier):
            carrier.set_service('fs', Provider())

    try:
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(MountProvider)
        caps = dict(limit=3, maxLineLength=2000, maxBytes=51200, streamMinSize=10)
        caps.update(fixture.get('caps', {}))
        mounted = await ctx.plugin(ToolFsPlugin, dict(readLimit=caps['limit'], readMaxLineLength=caps['maxLineLength'], readMaxBytes=caps['maxBytes'], readStreamMinSize=caps['streamMinSize']))
        ctx.on('fs/observed', lambda target, observation, execution: trace.append(dict(dict(kind='observed', path=target.displayPath), **observation)))
        agent = None if fixture.get('noAgent') else SimpleNamespace(session=SimpleNamespace(header=dict(cwd='C:/fixture')))
        tools = ctx.get('tools')
        result = await tools.execute(ToolExecutionInput(name='read', arguments=fixture['args'], call_id='read-fixture', signal=signal, agent=agent))
        value = dict(isError=result.isError, content=copy.deepcopy(result.content))
        for public, internal in (('value', 'value'), ('error', 'error'), ('meta', 'meta')):
            item = getattr(result, internal)
            if item is not None:
                value[public] = copy.deepcopy(item)
        if result.additional_contexts:
            value['additionalContexts'] = copy.deepcopy(result.additional_contexts)
        tool = tools.get('read')
        replay = []
        for name, damage in [('original', {}), ('error', dict(isError=True)), ('missing-meta', dict(meta=None)), ('bad-meta', dict(meta={})), ('wrong-envelope', dict(content=[dict(type='text', text='obsolete')])), ('extra-block', dict(content=value['content'] + [dict(type='text', text='extra')]))]:
            replay.append(dict(name=name, value=tool.present_result(fixture['args'], dict(value, **damage))))
        row = dict(name=fixture['name'], trace=trace, result=value, schema=next(item for item in tools.schemas() if item['name'] == 'read'), call=tool.present_call(fixture['args']), replay=replay)
        await mounted.dispose()
        row['afterUnload'] = tools.get('read') is not None
        return row
    finally:
        await ctx.fiber.dispose()


async def main():
    fixture_path = Path(__file__).resolve().parent / 'read_tool_fixtures_v1.json'
    fixtures = json.loads(fixture_path.read_text(encoding='utf-8'))
    rows = [await observe(fixture) for fixture in fixtures['cases']]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            modules[path.relative_to(selected_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(selected_root), executable=sys.executable, python=sys.version, modules=modules, fixtureSha256=hashlib.sha256(fixture_path.read_bytes()).hexdigest(), rows=rows), stream, ensure_ascii=True, indent=2)
        stream.write('\n')


asyncio.run(main())
