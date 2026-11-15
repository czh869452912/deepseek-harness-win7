"""Actual SDK stdio with candidate commands and v4 Agent input processing."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


async def main():
    from scripts.rc022_subagent_fixture import setup
    from scripts.oracles.generate_agent_machine_current_cases import response
    from dsh.interaction.commands_current import CurrentCommandRuntime
    from dsh.interaction.command_builtin import BUILTINS
    from dsh.llm.message import create_user_message
    from dsh.sdk.plugin import SdkJsonRpcPlugin
    root=Path(sys.argv[1]);fixture=await setup(root/'sessions',script=[response('query answer')]*3,directory=root)
    ctx=fixture.ctx;exited=asyncio.Event();ctx.set_service('appExit',lambda code:exited.set())
    async def handler(invocation):
        invocation.agent.followup(create_user_message(dict(source=dict(kind='user'),content=[dict(type='text',text='command input')])))
        return dict(kind='success',text='admitted')
    try:
        await ctx.plugin(CurrentCommandRuntime)
        ctx.commands.register(dict(name='design',definitionId=BUILTINS['plan'],description='query fixture',handler=handler))
        await ctx.plugin(SdkJsonRpcPlugin);await exited.wait()
    finally:await ctx.fiber.dispose()


if __name__=='__main__':asyncio.run(main())
