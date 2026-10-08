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
options = parser.parse_args()
root = options.root.resolve()
sys.path.insert(0, str(root))
from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.core.system_prompt import SystemPrompt
from dsh.core.abort import AbortController
from dsh.llm.llm_service import LlmRuntime
from dsh.subagent.runtime import SubagentPlugin
from dsh.subagent.canonical_tools import CanonicalToolSubagent


async def main():
    rows = []
    for reason in ('completed', 'aborted', 'error', 'max-tokens', 'refusal', 'provider-extra'):
        for diagnostic in (None, '', '具体失败 🧪'):
            for partial in (False, True):
                name = reason + '/' + ('absent' if diagnostic is None else 'empty' if diagnostic == '' else 'text') + '/' + str(partial).lower()
                terminal = dict(stopReason=reason, output=[dict(type='text', text='部分答案 🧪'),
                    dict(type='text', text='\nsecond line')] if partial else [])
                if diagnostic is not None:
                    terminal['diagnostic'] = diagnostic
                ctx, handle = Context(), None
                trace = dict(started=0, disposed=0)
                try:
                    for provider in (LlmRuntime, SessionPlugin, ToolsPlugin, SystemPrompt, AgentPlugin):
                        await ctx.plugin(provider)
                    await ctx.plugin(AgentLoopPlugin, dict(agents=[]))
                    await ctx.plugin(SubagentPlugin)

                    async def start(request):
                        trace['started'] += 1
                        settled = asyncio.get_running_loop().create_future()
                        settled.set_result(copy.deepcopy(terminal))

                        async def dispose():
                            trace['disposed'] += 1

                        return SimpleNamespace(id='foreground-fixed-run', result=settled, dispose=dispose)

                    ctx.get('subagents').registerProvider(SimpleNamespace(name='foreground-probe',
                        inheritsParentContext=False, capabilities=dict(depthLimit=True), start=start))

                    async def setup(agent_ctx):
                        await agent_ctx.plugin(CanonicalToolSubagent, dict(provider='foreground-probe', enableRunInBackground=False))

                    handle = await ctx.get('agents').create(dict(sessionId='foreground-fixed-parent', setup=setup))
                    result = await ctx.get('tools').execute(ToolExecutionInput(name='subagent',
                        arguments=dict(description='Actual failure consumer', prompt='Controlled provider terminal result'),
                        call_id='foreground-fixed-call', signal=AbortController().signal, agent=handle.agent))
                    public = dict(content=result.content, isError=result.is_error)
                    if not result.is_error:
                        public['value'] = result.value
                    if result.error is not None:
                        public['error'] = result.error
                    if result.meta is not None:
                        public['meta'] = result.meta
                    if result.additional_contexts:
                        public['additionalContexts'] = result.additional_contexts
                    if result.concludes_turn:
                        public['concludesTurn'] = True
                    rows.append(dict(name=name, terminal=terminal, trace=trace, result=public))
                finally:
                    if handle is not None:
                        await handle.dispose()
                    await ctx.fiber.dispose()
    modules = {}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_file() and root in path.parents and path.relative_to(root).parts[0] == 'dsh':
                modules[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), python=sys.version, executable=sys.executable, rows=rows, modules=modules,
            observerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), stream, ensure_ascii=True, indent=2)
        stream.write('\n')


asyncio.run(main())
