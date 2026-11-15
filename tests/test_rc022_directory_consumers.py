"""Actual current-directory consumers and the failure boundary before side effects."""
import pytest

from dsh.core.tools import ToolExecutionInput
from dsh.fs.tools_authorized import AuthorizedToolFs, AuthorizedToolFsSearch
from dsh.fs.tool_present_authorized import AuthorizedToolPresent
from dsh.session.tool_working_directory import ToolWorkingDirectory
from dsh.subprocess.local import LocalSubprocessRuntime
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_switch_changes_actual_files_search_index_shell_and_durable_delivery(tmp_path):
    from scripts.rc022_directory_consumers_probe import observe
    rows = {row['name']: row for row in await observe(tmp_path)}
    for name in ('initial-directory', 'changed-directory', 'read', 'write', 'edit',
                 'glob', 'grep', 'shell', 'relative-shell', 'present'):
        assert not rows[name]['result']['isError'], rows[name]
    assert rows['shell-cwd']['values'] == ['<work>/moved', '<work>']
    assert rows['shell']['result']['value']['cwd'] == '<work>/moved'
    assert rows['moved-completion']['oldRetired']
    assert rows['read']['result']['value']['lines'] == [dict(number=1, text='before')]
    assert rows['glob']['result']['value']['paths'] == ['created.txt', 'current.txt']
    assert rows['grep']['result']['value']['matches'] == [dict(path='current.txt', lineNumber=1, line='after')]
    assert rows['delivery-record']['files'] == [[dict(path='<work>/moved/created.txt', description='Output')]]
    assert rows['original-header'] == dict(name='original-header', cwd='<work>', current='<work>/moved',
                                          createdAtOriginal=False, changedFile='after\n')
    assert rows['errors']['empty']['isError'] and rows['errors']['noAgent']['isError']
    assert rows['provider-unload'] == dict(name='provider-unload', searches=0, subprocessGone=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('name,arguments', [
    ('read', dict(file_path='file.txt')),
    ('write', dict(file_path='created.txt', content='created')),
    ('edit', dict(file_path='file.txt', old_string='before', new_string='after')),
    ('glob', dict(pattern='*.txt')),
    ('grep', dict(pattern='before', path='file.txt')),
    ('present', dict(files=[dict(path='file.txt')])),
    ('working_directory', {}),
])
async def test_directory_failure_prevents_file_and_delivery_side_effects(tmp_path, name, arguments):
    fixture = await setup(tmp_path/'fixture', directory=tmp_path)
    ctx = fixture.ctx
    (tmp_path/'file.txt').write_text('before', encoding='utf-8')
    async def unavailable(*args):
        raise RuntimeError('directory unavailable')
    ctx.workingDirectory.ensure = unavailable
    try:
        for plugin in (LocalSubprocessRuntime, AuthorizedToolFs, AuthorizedToolFsSearch, AuthorizedToolPresent, ToolWorkingDirectory):
            await ctx.plugin(plugin, dict(sampleOverCapGlobResults=False) if plugin is AuthorizedToolFsSearch else None)
        handle = await ctx.agents.create(dict(sessionId='failure', meta=dict(cwd=str(tmp_path)),
                                             agentOptions=dict(provider='script', model='model')))
        agent = handle.agent
        agent.session.append('turn/start', dict(turn=1))
        result = await ctx.tools.execute(ToolExecutionInput('failure-call', name, arguments,
                                                          agent=agent, signal=fixture.signal))
        assert result.isError and 'directory unavailable' in str(result.content)
        assert (tmp_path/'file.txt').read_text(encoding='utf-8') == 'before'
        assert not (tmp_path/'created.txt').exists()
        assert not any(event['type'] == 'deliverables/presented' for event in agent.session.snapshotEvents())
    finally:
        await ctx.fiber.dispose()
