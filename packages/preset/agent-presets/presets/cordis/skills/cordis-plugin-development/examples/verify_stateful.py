"""Trusted external verifier for stateful.host.py, not dynamic plugin source.

Run with the installation's Python: verify_stateful.py INSTALL_ROOT SOURCE [TOOL].
Creates a private canonical Web profile and closes it without a model request.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile


async def verify(install_root, source, tool_name='win7_state_counter'):
    sys.path.insert(0, str(install_root))
    from dsh.boot.profile_boot import run_profile
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.tools import ToolExecutionInput

    with tempfile.TemporaryDirectory(prefix='dsh-state-verify-') as folder:
        home = Path(folder) / 'home'
        previous = {name: os.environ.get(name) for name in ('DSH_HOME', 'DSH_AGENTS_HOME', 'DSH_TELEMETRY_MODE')}
        os.environ['DSH_HOME'] = str(home)
        os.environ['DSH_AGENTS_HOME'] = str(Path(folder) / 'empty-agents')
        os.environ['DSH_TELEMETRY_MODE'] = 'DISABLED'
        result = None
        try:
            result = await run_profile(dict(profile='web', dshHome=str(home),
                args=['--no-open', '--port', '0'], waitForExit=False))
            ctx = result['ctx']
            await ctx.get('sessionController').create(dict(sessionId='state-verify',
                cwd=str(source.parent), agentPreset='cordis'))
            agent = ctx.get('agents').get('state-verify')
            runner, tools = ctx.get('dynamicCordisRunner'), ctx.get('tools')
            receipt = runner.define(dict(sessionId=agent.id, plugin=dict(kind='new', idPrefix='probe'),
                name='Stateful verification', purpose='Verify lifecycle in a private profile',
                code=dict(host=source.read_text(encoding='utf-8-sig'))))
            started = await runner.run(agent, receipt['pluginId'], receipt['packageId'], 'run')
            assert started['ok'], started

            async def call():
                answer = await tools.execute(ToolExecutionInput('state-check', tool_name, {},
                    agent=agent, signal=NEVER_ABORTED))
                assert not answer.is_error, answer.error
                return answer.value

            assert [await call(), await call()] == [1, 2]
            state = ctx.get('win7AuthoringStateful')
            assert state is not None
            ctx.emit('win7-authoring/ping', 1)
            assert state['events'] == 1
            for _ in range(100):
                if state['ticks']:
                    break
                await asyncio.sleep(0.01)
            assert state['ticks'] > 0
            assert (await runner.stop(agent, receipt['pluginId']))['ok']
            assert state['active'] is False
            assert ctx.get('win7AuthoringStateful') is None
            stopped = dict(state)
            ctx.emit('win7-authoring/ping', 2)
            await asyncio.sleep(0.1)
            assert state == stopped
            gone = await tools.execute(ToolExecutionInput('state-gone', tool_name, {},
                agent=agent, signal=NEVER_ABORTED))
            assert gone.is_error
            assert (await runner.run(agent, receipt['pluginId'], receipt['packageId'], 'run'))['ok']
            assert await call() == 1
            assert state == stopped
            return dict(passed=True, values=[1, 2, 1], eventObserved=True,
                        timerObserved=True, stoppedStateStable=True, oldToolRevoked=True)
        finally:
            try:
                if result is not None:
                    result['shutdown'].shutdown(0)
                    await result['shutdown'].wait()
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        raise SystemExit('Usage: verify_stateful.py INSTALL_ROOT SOURCE [TOOL]')
    answer = asyncio.run(verify(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(),
                               sys.argv[3] if len(sys.argv) == 4 else 'win7_state_counter'))
    print(json.dumps(answer, ensure_ascii=True))
