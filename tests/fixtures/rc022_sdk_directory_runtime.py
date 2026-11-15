"""Actual SDK plugin over child stdio, with explicit candidate v4 composition."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


async def main():
    from scripts.rc022_subagent_fixture import setup
    from dsh.sdk.plugin import SdkJsonRpcPlugin
    root=Path(sys.argv[1]);fixture=await setup(root/'sessions',script=[],directory=root)
    exited=asyncio.Event();fixture.ctx.set_service('appExit',lambda code:exited.set())
    try:
        await fixture.ctx.plugin(SdkJsonRpcPlugin)
        await exited.wait()
    finally:await fixture.ctx.fiber.dispose()


if __name__=='__main__':asyncio.run(main())
