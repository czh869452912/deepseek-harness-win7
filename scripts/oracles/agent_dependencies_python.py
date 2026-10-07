import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
ROOT = options.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.llm.llm_service import LlmRuntime


SERVICES = ('agents', 'sessions', 'llm', 'tools', 'systemPrompt')
PROVIDERS = dict(agents=AgentPlugin, sessions=SessionPlugin, llm=LlmRuntime,
    tools=ToolsPlugin, systemPrompt=SystemPrompt)


async def settle():
    for position in range(8):
        await asyncio.sleep(0)


def project(ctx, fiber):
    return dict(active=fiber.state == FiberState.ACTIVE, pending=fiber.state == FiberState.PENDING,
        loop=ctx.get('agentLoop') is not None,
        services={name: ctx.get(name) is not None for name in SERVICES})


async def main():
    rows = []
    ctx = Context()
    try:
        loop = await ctx.plugin(AgentLoopPlugin, dict(agents=[]))
        rows.append(dict(name='initial-missing', **project(ctx, loop)))
        for name in ('systemPrompt', 'tools', 'llm', 'agents', 'sessions'):
            await ctx.plugin(PROVIDERS[name])
            await settle()
            rows.append(dict(name='provide-' + name, **project(ctx, loop)))
    finally:
        await ctx.fiber.dispose()
    for name in SERVICES:
        ctx = Context()
        handle = None
        try:
            fibers = {}
            for service in SERVICES:
                fibers[service] = await ctx.plugin(PROVIDERS[service])
            loop = await ctx.plugin(AgentLoopPlugin, dict(agents=[]))
            await settle()
            factory, registry = ctx.get('agentLoop'), ctx.get('agents')
            identity = 'dependency-' + name
            handle = await registry.create(session_id=identity)
            rows.append(dict(name=name + '/before-loss', published=registry.get(identity) is handle.agent,
                **project(ctx, loop)))
            await fibers[name].dispose()
            await settle()
            rows.append(dict(name=name + '/after-loss', published=registry.get(identity) is not None,
                **project(ctx, loop)))
            try:
                late = await factory.create_agent(session_id='late-' + name, owner_ctx=ctx)
                await late.dispose()
                old_factory = dict(accepted=True)
            except Exception as error:
                old_factory = dict(message=str(error))
            rows.append(dict(name=name + '/retired-factory', result=old_factory))
            await ctx.plugin(PROVIDERS[name])
            await settle()
            rows.append(dict(name=name + '/restored', replacement=ctx.get('agentLoop') is not factory,
                **project(ctx, loop)))
            try:
                current = await ctx.get('agents').create(session_id='restored-' + name)
                rows.append(dict(name=name + '/restored-create',
                    published=ctx.get('agents').get(current.agent.id) is current.agent))
                await current.dispose()
            except Exception as error:
                rows.append(dict(name=name + '/restored-create', error=dict(message=str(error))))
            await loop.dispose()
            await settle()
            rows.append(dict(name=name + '/final-disposal', loop=ctx.get('agentLoop') is not None))
        finally:
            if handle is not None:
                await handle.dispose()
            await ctx.fiber.dispose()
    return rows


rows = asyncio.run(main())
imports = {}
for name, module in sorted(sys.modules.items()):
    filename = getattr(module, '__file__', None)
    if filename and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(filename).resolve()
        imports[selected.relative_to(ROOT).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
report = dict(root=str(ROOT), python=sys.version, executable=sys.executable, imports=imports, rows=rows,
    fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
with options.output.open('x', encoding='utf-8') as stream:
    json.dump(report, stream, indent=2)
    stream.write('\n')
