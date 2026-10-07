"""Fresh-process probe of the default profile's public Agent resume service."""
import asyncio
import json
import os
import sys

from dsh.boot.app_boot import boot, load_layered_env
from dsh.boot.cmdline import provide_cmdline
from dsh.boot.profile_boot import compose_profile, create_app_ready, PROFILE_ROOT_FILENAME
from dsh.cordis.environment import DSH_LAUNCH_ENVIRONMENT_KEY
from dsh.llm.message import create_user_message


async def main():
    composed = await compose_profile('headless', [], dsh_home=os.environ['DSH_HOME'])

    def setup(ctx):
        ctx.provide(DSH_LAUNCH_ENVIRONMENT_KEY, load_layered_env('dsh'))
        # Boot the real rows; leave the one-shot app runner waiting while this
        # probe calls the same public Agent service a resumable app consumes.
        provide_cmdline(ctx, dict(args=['resume-probe'], exit=lambda code: None, ready=create_app_ready()['service']))

    ctx = await boot('dsh', os.path.join(composed.profile.dir, PROFILE_ROOT_FILENAME), composed.all_patches(), setup)
    try:
        handle = await ctx.get('agents').resume(sys.argv[1], options=ctx.get('agentDefaultModel').current_selection())
        agent = handle.agent
        before = agent.session.seq
        assert any(event['type'] == 'tool/result' for event in agent.session.events)
        agent.followup(create_user_message(dict(content=[dict(type='text', text='Continue from the restored file inspection')], source=dict(kind='user'))))
        await agent.when_idle()
        await ctx.get('sessions').flush(agent.session)
        endings = [event for event in agent.session.events if event['seq'] >= before and event['type'] == 'turn/end']
        assert endings[-1]['data']['reason']['kind'] == 'completed', endings
        print(json.dumps(dict(restored=sys.argv[1], before=before, after=agent.session.seq)))
    finally:
        await ctx.fiber.dispose()


if __name__ == '__main__':
    asyncio.run(main())
