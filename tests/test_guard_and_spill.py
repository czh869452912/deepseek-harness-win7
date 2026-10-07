from dsh.core.system_prompt import SystemPrompt as SourceToolsPrompt
import os
import shutil
import tempfile
import pytest
from dsh.guard.repeat_tool_reminder import RepeatToolReminderPlugin, GENTLE_REMINDER
from dsh.spill.spill_store import SpillStore


def test_repeat_tool_reminder_guard():
    plugin = RepeatToolReminderPlugin(config={"thresholds": [3, 5, 8]})
    session_id = "test-session"

    # Call 1 & 2: no reminder
    assert plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"}) is None
    assert plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"}) is None

    # Call 3: triggers gentle reminder
    rem3 = plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"})
    assert rem3 == GENTLE_REMINDER

    # Call 4: no reminder
    assert plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"}) is None

    # Call 5: triggers detailed reminder
    rem5 = plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"})
    assert "Repeated tool call detected:" in rem5
    assert "consecutive_calls: 5" in rem5


def test_spill_store():
    tmpdir = tempfile.mkdtemp()
    store = SpillStore(root=tmpdir)

    large_text = "A" * 100000
    spill_file = store.write_spill(large_text)
    assert os.path.exists(spill_file)

    recovered = store.read_spill(spill_file)
    assert recovered == large_text

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_repeat_guard_preserves_downstream_decision_isolates_agents_and_resets_only_user_input():
    from dsh.cordis.context import Context
    from dsh.core.agent import Agent
    from dsh.core.session import Session
    from dsh.core.tools import ToolsPlugin
    from types import SimpleNamespace

    ctx = Context()
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin)
    fiber = await ctx.plugin(RepeatToolReminderPlugin, dict(thresholds=[2]))
    first, second = Agent(Session('first')), Agent(Session('second'))
    downstream = dict(kind='block', feedback=[dict(type='text', text='denied')],
                      additionalContexts=[dict(source=dict(kind='plugin', plugin='later'), content=[])])
    async def block(*args):
        return downstream
    ctx.on('tools/post-execute', block)
    async def attempt(agent):
        return await ctx.waterfall('tools/post-execute', SimpleNamespace(agent=agent, name='view', arguments={}), None)
    try:
        assert await attempt(first) is downstream
        assert await attempt(second) is downstream
        repeat = await attempt(first)
        assert repeat['kind'] == 'block' and repeat['feedback'] == downstream['feedback']
        assert len(repeat['additionalContexts']) == 2
        assert repeat['additionalContexts'][0]['source']['form'] == 'notice'
        assert repeat['additionalContexts'][1] is downstream['additionalContexts'][0]
        assert len(downstream['additionalContexts']) == 1
        await ctx.waterfall('agent/pre-step', dict(agent=second, messages=[dict(source=dict(kind='plugin'))]))
        assert len((await attempt(second))['additionalContexts']) == 2
        await ctx.waterfall('agent/pre-step', dict(agent=first, messages=[dict(source=dict(kind='user'))]))
        assert await attempt(first) is downstream
        await fiber.dispose()
        assert await attempt(first) is downstream
    finally:
        await ctx.fiber.dispose()
