"""Exercise actual Loader/executor selection with the fixed base rows."""
import asyncio
import json
import os
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def inputs(source):
    class Loader(yaml.SafeLoader):
        pass
    Loader.add_constructor('tag:yaml.org,2002:js', lambda loader,node: loader.construct_scalar(node))
    base = source/'packages/bundle/base/cordis.patch.yml'
    entries = yaml.load(base.read_text(encoding='utf-8'), Loader=Loader)[0]['insert']
    ids = ('tools', 'tool-executor-native', 'tool-executor-ptc', 'ptc-runtime', 'system-prompt')
    rows = [row for row in entries if row['id'] in ids]
    assert len(rows) == len(ids)
    return dict(rows=rows, ptc=yaml.safe_load((source/'apps/cli/config/examples/ptc.yml').read_text(encoding='utf-8')))


async def observe(data=None):
    from dsh.cordis import Context, Loader
    from dsh.boot.profile import compose_entries
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.core.tool_executor_ptc import PtcToolExecutorPlugin
    from dsh.code_runtime.confined_ptc import ConfinedPythonPtcRuntime
    from dsh.sandbox.local import LocalSandboxProvider
    from dsh.sandbox.sandbox_policy import SandboxPolicyService
    data = data or inputs(ROOT/'reference')
    result = []
    original = os.environ.get('DSH_TOOLS_MODE')
    try:
        for action in ('native', 'env-ptc', 'ptc', 'env-native', 'missing', 'duplicate', 'mode-native', 'mode-null', 'parallel'):
            os.environ['DSH_TOOLS_MODE'] = 'ptc' if action == 'env-ptc' else 'native'
            patches = []
            if action in ('ptc', 'env-native'):
                patches = data['ptc'][:2]
            elif action == 'missing':
                patches = [dict(id='tool-executor-native', disabled=True)]
            elif action == 'duplicate':
                patches = [dict(id='tool-executor-ptc', disabled=False)]
            elif action.startswith('mode-'):
                patches = [dict(id='tools', config=dict(mode=None if action == 'mode-null' else 'native'))]
            elif action == 'parallel':
                patches = [dict(id='tools', config=dict(maxParallelSubCalls=2))]
            overlay = yaml.safe_load((ROOT/'migration/candidates/rc022/overlays/ptc-python.yml').read_text(encoding='utf-8'))
            rows = compose_entries([[dict(insert=data['rows'])], overlay, patches])
            assert next(row for row in rows if row['id'] == 'ptc-runtime')['disabled'] is True
            assert next(row for row in rows if row['id'] == 'ptc-runtime-python')['name'] == '@deepseek-ai/dsh-ptc-runtime-python'
            ctx = Context()
            await ctx.plugin(Loader)
            await ctx.plugin(SandboxPolicyService)
            await ctx.plugin(LocalSandboxProvider)
            classes = dict(zip(('tools', 'tool-executor-native', 'tool-executor-ptc', 'ptc-runtime', 'system-prompt'),
                (CurrentToolsPlugin, NativeToolExecutorPlugin, PtcToolExecutorPlugin, ConfinedPythonPtcRuntime, SystemPrompt)))
            classes['ptc-runtime-python'] = ConfinedPythonPtcRuntime
            # Loader builtins use cordis: references; preserve real row names in
            # inputs and translate only the fixture's module lookup mechanism.
            builtins = ctx.loader.builtins
            for row in rows:
                key = row['id']
                builtins[key] = classes[key]
                row['name'] = 'cordis:' + key
            failures = []
            try:
                for row in rows:
                    await ctx.loader.create(row)
                await ctx.loader.wait()
                for row in rows:
                    fiber = ctx.loader.store[row['id']].fiber
                    if fiber is not None:
                        try:
                            await fiber
                        except Exception:
                            failures.append(row['id'])
                names = None
                code = None
                if ctx.get('tools') is not None:
                    try:
                        names = [schema['name'] for schema in (await ctx.systemPrompt.assemble({}))['tools']]
                    except Exception as error:
                        code = getattr(error, 'code', type(error).__name__)
                result.append(dict(action=action, failed=sorted(failures), names=names, code=code,
                    runtime=ctx.get('ptcRuntime') is not None))
            finally:
                await ctx.fiber.dispose()
    finally:
        if original is None:
            os.environ.pop('DSH_TOOLS_MODE', None)
        else:
            os.environ['DSH_TOOLS_MODE'] = original
    return result


def prepare(output):
    source = Path(sys.argv[sys.argv.index('--source')+1]).resolve()
    data = inputs(source)
    path = output/'composition.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    async def prepared():
        return await observe(data)
    probe.native = prepared
    return [path, source/'packages/bundle/base/cordis.patch.yml', source/'apps/cli/config/examples/ptc.yml']


if __name__ == '__main__':
    probe.main('rc022_executor_composition.mts', 'Actual Loader activation of fixed base native/PTC rows, removed configuration and ignored environment switches. Python provider is an explicit Win7 overlay, not Node ABI parity.',
        [Path(__file__).resolve(), ROOT/'dsh/core/tools.py', ROOT/'migration/candidates/rc022/overlays/ptc-python.yml'], prepare=prepare)
