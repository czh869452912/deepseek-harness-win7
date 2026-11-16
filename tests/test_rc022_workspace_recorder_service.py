import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.core.abort import NEVER_ABORTED
from dsh.deliverables.workspace_changes import CurrentWorkspaceChanges
from dsh.llm.message import create_user_message
from scripts.oracles.generate_agent_machine_current_cases import response
from scripts.rc022_candidate_fixture import setup
from scripts.rc022_change_git_probe import git, repo_state


def tool(identity, name, arguments):
    call = dict(type='tool-call', id=identity, name=name, arguments=json.dumps(arguments))
    return [dict(type='block-start', index=0, blockType='tool-call'),
            dict(type='tool-call-delta', index=0, id=identity, name=name, argumentsDelta=call['arguments']),
            dict(type='block-end', index=0, block=call), dict(type='finish', reason=dict(kind='tool-calls'))]


@pytest.mark.asyncio
@pytest.mark.parametrize('repository', [False, True])
async def test_actual_v4_agent_tool_policy_session_and_service_lifetimes(tmp_path, monkeypatch, repository):
    workspace = tmp_path/'w'
    workspace.mkdir()
    if repository:
        git(workspace, 'init', '-q')
        git(workspace, 'config', 'user.name', 'Fixture')
        git(workspace, 'config', 'user.email', 'fixture@example.invalid')
        git(workspace, 'config', 'core.autocrlf', 'false')
        (workspace/'.gitignore').write_bytes(b'ignored\n')
        (workspace/'prior').write_bytes(b'committed\n')
        git(workspace, 'add', '--all')
        git(workspace, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
        (workspace/'prior').write_bytes(b'user uncommitted\n')
        before = repo_state(workspace)
    script = [tool('write-call', 'write', dict(file_path='new', content='first\n')),
              tool('edit-call', 'edit', dict(file_path='new', old_string='first', new_string='second')),
              tool('ignored-call', 'write', dict(file_path='ignored', content='captured\n')), response('done')]
    runtime = tmp_path/'r'
    runtime.mkdir()
    ctx = await setup(runtime, extra=[('subprocess-local', {}), ('workspace-changes', {}),
        ('fs-observation-policy', {}), ('tool-fs', dict(readImage=False))], script=script)
    if not repository:
        async def unavailable(*_):
            raise FileNotFoundError('git unavailable')
        monkeypatch.setattr(ctx.subprocess, 'resolveExecutable', unavailable)
    handle = None
    scratch_before = set(Path(tempfile.gettempdir()).glob('dsh-workspace-changes-*'))
    try:
        handle = await ctx.agents.create(dict(sessionId='changes', meta=dict(cwd=str(workspace)),
                                              agentOptions=dict(provider='script', model='model')))
        handle.agent.followup(create_user_message(dict(content=[dict(type='text', text='edit files')], source=dict(kind='input'))))
        await handle.agent.whenIdle()
        session = handle.agent.session
        events = session.snapshotEvents()
        (tmp_path/'workspace-events-observations.json').write_text(json.dumps(events, default=str, indent=2), encoding='utf-8')
        changes = [event for event in events if event['type'] == 'workspace/changes']
        assert len(changes) == 1
        event = changes[0]
        summary = ctx.workspaceChanges.summary(session.id, event['seq'])
        assert [file['path'] for file in summary['files']] == ['ignored', 'new']
        assert summary['total'] == 2 and summary['added'] == 2 and summary['deleted'] == 0
        assert ('snapshot' in summary) is repository
        assert event['seq'] < next(item['seq'] for item in events if item['type'] == 'turn/end')
        diffs = [await ctx.workspaceChanges.diff(session.id, event['seq'], index, NEVER_ABORTED) for index in range(2)]
        assert diffs[1]['before'] is False and diffs[1]['after'] is True
        assert diffs[1]['hunks'][0]['lines'] == ['+second']
        assert await ctx.workspaceChanges.diff('missing', 0, 0, NEVER_ABORTED) is None
        assert await ctx.workspaceChanges.diff(session.id, event['seq'], -1, NEVER_ABORTED) is None
        if repository:
            assert repo_state(workspace) == before
        (tmp_path/'workspace-service-observations.json').write_text(json.dumps(dict(
            summary=summary, diffs=diffs, events=[item['type'] for item in events]), indent=2), encoding='utf-8')
        await handle.dispose()
        handle = None
        assert ctx.workspaceChanges.summary(session.id, event['seq']) is None
    finally:
        if handle is not None:
            await handle.dispose()
        await ctx.fiber.dispose()
    assert ctx.get('workspaceChanges') is None
    assert set(Path(tempfile.gettempdir()).glob('dsh-workspace-changes-*')) == scratch_before


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['timeoutMs', 'outputMaxBytes', 'maxFiles', 'maxFileBytes', 'diffTimeoutMs'])
async def test_nonpositive_limits_reject_before_registering_service(tmp_path, field):
    from dsh.cordis.context import Context
    from dsh.fs.local_current import CurrentFsLocal
    from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
    ctx = Context()
    try:
        await ctx.plugin(CurrentFsLocal, dict(cwd=str(tmp_path)))
        await ctx.plugin(AuthorizedLocalSubprocessRuntime)
        with pytest.raises(ValueError, match='positive integer '+field):
            await ctx.plugin(CurrentWorkspaceChanges, {field: 0})
        assert ctx.get('workspaceChanges') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_ineligible_sessions_never_resolve_git_and_unload_withdraws_hooks(tmp_path):
    from dsh.cordis.context import Context
    from dsh.core.runtime_v4 import SessionV4Plugin
    from dsh.fs.local_current import CurrentFsLocal
    from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
    ctx = Context()
    calls = []
    try:
        await ctx.plugin(SessionV4Plugin)
        await ctx.plugin(CurrentFsLocal, dict(cwd=str(tmp_path)))
        await ctx.plugin(AuthorizedLocalSubprocessRuntime)
        async def unavailable(*args):
            calls.append(args[0])
            raise FileNotFoundError('git unavailable')
        ctx.subprocess.resolveExecutable = unavailable
        fiber = await ctx.plugin(CurrentWorkspaceChanges)
        for index, meta in enumerate([{}, dict(cwd=str(tmp_path), origin='subagent'), dict(cwd=str(tmp_path), delegationDepth=1)]):
            session = ctx.sessions.create('ineligible-'+str(index), dict(meta=meta))
            session.append('turn/start', dict(turn=1))
            await ctx.serial('agent/turn-stopping', dict(agent=SimpleNamespace(session=session), turn=1))
            assert ctx.workspaceChanges.summary(session.id, 0) is None
        assert calls == []
        await fiber.dispose()
        assert ctx.get('workspaceChanges') is None
        session = ctx.sessions.create('after-unload', dict(meta=dict(cwd=str(tmp_path))))
        session.append('turn/start', dict(turn=1))
        await ctx.serial('agent/turn-stopping', dict(agent=SimpleNamespace(session=session), turn=1))
        assert calls == []
    finally:
        await ctx.fiber.dispose()
