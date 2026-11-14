"""Path-only completion, shared cancellation, refresh and Remote ownership."""
import asyncio
import copy

import pytest

from dsh.api.session_catalogs import SessionFileReferences
from dsh.cordis.context import Context
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.scope import create_scope, scope_of
from dsh.core.session import SessionStore
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.context.file_reference_local import LocalFileReferenceService, FILE_REFERENCE_PROMPT
from dsh.context.file_reference_local.search import WorkspaceFileSearch
from dsh.typert.dispatch import RemoteDispatcher
from dsh.typert.registry import TypertRegistry


@pytest.mark.asyncio
async def test_live_directory_and_bounded_fuzzy_candidates_exclude_generated_and_hidden_paths(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "中文 name.py").write_text("not a candidate payload", encoding="utf-8")
    (tmp_path / "..source").mkdir()
    (tmp_path / ".secret.py").write_text("hidden", encoding="utf-8")
    for name in ("dist", "node_modules", ".venv"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "sample.py").write_text("generated", encoding="utf-8")
    search = WorkspaceFileSearch(str(tmp_path))
    try:
        assert await search.list("") == [dict(path="src", kind="directory")]
        assert await search.list("src/") == [dict(path="src/中文 name.py", kind="file")]
        assert await search.list("src" + chr(92)) == await search.list("src/")
        assert await search.list("中文") == [dict(path="src/中文 name.py", kind="file")]
        assert await search.list("secret") == []
        assert await search.list(".secret") == [dict(path=".secret.py", kind="file")]
        assert await search.list("dist/") == []
        assert await search.list("../") == []
        # A basename beginning with two dots is still inside the workspace.
        assert await search.list("..source/") == []
        (tmp_path / "..source" / "inside.py").write_text("inside", encoding="utf-8")
        assert await search.list("..source/") == [dict(path="..source/inside.py", kind="file")]
    finally:
        search.dispose()
        await search.drain()


@pytest.mark.asyncio
async def test_entry_and_result_limits_are_independent(tmp_path):
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    search = WorkspaceFileSearch(str(tmp_path), dict(maxEntries=2, maxResults=1))
    try:
        assert await search.list("py") == [dict(path="a.py", kind="file")]
        assert await search.list("c") == []
        # Directory queries use current state, independently of the global index budget.
        assert await search.list("./c") == [dict(path="./c.py", kind="file")]
    finally:
        search.dispose()
        await search.drain()


@pytest.mark.asyncio
async def test_one_cancelled_caller_keeps_the_shared_traversal_for_another_query(tmp_path, monkeypatch):
    (tmp_path / "sample.py").write_text("", encoding="utf-8")
    search = WorkspaceFileSearch(str(tmp_path))
    entered, release = asyncio.Event(), asyncio.Event()
    original = search.read_directory

    async def read(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(search, "read_directory", read)
    first_signal = AbortController()
    first = asyncio.ensure_future(search.list("sample", first_signal.signal))
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        second = asyncio.ensure_future(search.list("py"))
        failure = RuntimeError("cancel only the first waiter")
        first_signal.abort(failure)
        with pytest.raises(RuntimeError) as error:
            await first
        assert error.value is failure
        release.set()
        assert await second == [dict(path="sample.py", kind="file")]
    finally:
        release.set()
        search.dispose()
        await search.drain()
        await asyncio.gather(*[task for task in (first, second) if task is not None], return_exceptions=True)


@pytest.mark.asyncio
async def test_stale_index_answers_during_refresh_and_retries_after_root_failure(tmp_path, monkeypatch):
    (tmp_path / "a-old.py").write_text("", encoding="utf-8")
    search = WorkspaceFileSearch(str(tmp_path))
    try:
        previous = await search.list("a-")
        (tmp_path / "a-new.py").write_text("", encoding="utf-8")
        original = search.read_directory

        async def unavailable(*args, **kwargs):
            raise OSError("workspace root temporarily unavailable")

        monkeypatch.setattr(search, "read_directory", unavailable)
        search.invalidate()
        assert await search.list("a-") == previous
        await search.drain()
        assert await search.list("a-") == previous
        await search.drain()
        monkeypatch.setattr(search, "read_directory", original)
        assert await search.list("a-") == previous
        await search.drain()
        assert await search.list("a-") == [dict(path="a-new.py", kind="file"), dict(path="a-old.py", kind="file")]
    finally:
        search.dispose()
        await search.drain()


@pytest.mark.asyncio
async def test_dispose_aborts_pending_generation_and_preaborted_calls_keep_the_reason(tmp_path, monkeypatch):
    search = WorkspaceFileSearch(str(tmp_path))
    entered, release = asyncio.Event(), asyncio.Event()
    original = search.read_directory

    async def read(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(search, "read_directory", read)
    pending = asyncio.ensure_future(search.list("file"))
    await asyncio.wait_for(entered.wait(), 2)
    search.dispose()
    release.set()
    with pytest.raises(RuntimeError, match="disposed"):
        await pending
    await search.drain()
    assert await search.list("file") == []
    controller = AbortController()
    failure = RuntimeError("already cancelled")
    controller.abort(failure)
    with pytest.raises(RuntimeError) as error:
        await search.list("", controller.signal)
    assert error.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [False, None, "cancel", 0])
async def test_pending_caller_normalizes_non_exception_abort_reason_without_losing_cause(tmp_path, monkeypatch, reason):
    search = WorkspaceFileSearch(str(tmp_path))
    entered, release = asyncio.Event(), asyncio.Event()

    async def scan(signal):
        entered.set()
        await release.wait()
        signal.throw_if_aborted()
        return []

    monkeypatch.setattr(search, "scan_workspace", scan)
    controller = AbortController()
    pending = asyncio.ensure_future(search.list("file", controller.signal))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        controller.abort(reason)
        with pytest.raises(RuntimeError, match="^file search aborted$") as error:
            await pending
        assert error.value.cause is reason
        assert not controller.signal._listeners
        release.set()
        assert await search.list("other") == []
    finally:
        release.set()
        search.dispose()
        await search.drain()


@pytest.mark.parametrize('config', [dict(maxResults=0), dict(maxResults=True), dict(maxEntries=-1),
    dict(maxEntries=1.5), dict(maxEntries=9007199254740992), dict(excludedDirectories=[""]),
    dict(excludedDirectories=["a/b"]), dict(excludedDirectories=["a" + chr(92) + "b"]),
    dict(excludedDirectories=[None])])
def test_invalid_configuration_fails_before_discovery(tmp_path, config):
    with pytest.raises(ValueError):
        WorkspaceFileSearch(str(tmp_path), config)


@pytest.mark.asyncio
async def test_whole_number_json_limits_are_admitted_as_javascript_numbers(tmp_path):
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    search = WorkspaceFileSearch(str(tmp_path), dict(maxEntries=2.0, maxResults=1.0))
    try:
        assert await search.list("py") == [dict(path="a.py", kind="file")]
    finally:
        search.dispose()
        await search.drain()


@pytest.mark.asyncio
async def test_remote_agent_routing_scoped_guidance_refresh_and_service_unload(tmp_path):
    ctx = Context()
    scopes = []
    try:
        for plugin in (TypertRegistry, SessionStore, AgentPlugin, SystemPrompt, ToolsPlugin):
            await ctx.plugin(plugin)
        agents = []
        for sid in ("first", "second"):
            workspace = tmp_path / sid
            workspace.mkdir()
            (workspace / (sid + ".py")).write_text("PRIVATE_FILE_BODY", encoding="utf-8")
            scope = create_scope(ctx, sid)
            scopes.append(scope)
            session = ctx.get("sessions").create(sid, dict(meta=dict(cwd=str(workspace))))
            agent = Agent(session=session, ctx=scope.ctx)
            ctx.get("agents").register(agent)
            agents.append(agent)
        owner = await ctx.plugin(LocalFileReferenceService)
        await ctx.plugin(SessionFileReferences)
        remote = RemoteDispatcher(ctx)

        async def candidates(agent, query=""):
            return await remote.invoke(dict(namespace="fileReferences", method="list",
                args=dict(agentId=agent.id, query=query)))

        assert await candidates(agents[0]) == [dict(path="first.py", kind="file")]
        assert await candidates(agents[1]) == [dict(path="second.py", kind="file")]
        assert await candidates(agents[0], "first") == [dict(path="first.py", kind="file")]
        prompt = ctx.get("systemPrompt")
        assembly = await prompt.assemble(dict(scope=scope_of(agents[0].ctx)))
        assert next(s["text"] for s in assembly["sections"] if s["name"] == "context:file-reference") == ""
        remove_read = agents[0].ctx.get("tools").register_legacy("read", description="test read", parameters={}, handler=lambda args: None)
        assembly = await prompt.assemble(dict(scope=scope_of(agents[0].ctx)))
        assert next(s["text"] for s in assembly["sections"] if s["name"] == "context:file-reference") == FILE_REFERENCE_PROMPT
        payload = dict(messages=[dict(role="user", content="Inspect @first.py")])
        before = copy.deepcopy(payload)
        await ctx.waterfall("agent/pre-step", payload, lambda: payload)
        assert payload == before
        (tmp_path / "first" / "first-new.py").write_text("", encoding="utf-8")
        ctx.emit("session/event", agents[0].session, dict(type="tool/result"))
        assert await candidates(agents[0], "first") == [dict(path="first.py", kind="file")]
        await ctx.get("fileReferences").searches[agents[0]].drain()
        assert len(await candidates(agents[0], "first")) == 2
        remove_read()
        await owner.dispose()
        assert ctx.get("fileReferences") is None
        assert not any(s["name"] == "context:file-reference" for s in (await prompt.assemble(dict(scope=scope_of(agents[0].ctx))))["sections"])
    finally:
        for scope in scopes:
            await scope.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("preset", ["minimal", "standard", "cordis"])
async def test_canonical_web_profile_discovers_two_workspaces_without_reading_bodies(tmp_path, monkeypatch, preset):
    from canonical_web_fixture import web_context, close_web_context
    from dsh.core.scope import scope_of
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = await web_context(tmp_path / "home")
    try:
        remote = RemoteDispatcher(ctx)
        for name in ("one", "two"):
            workspace = tmp_path / name
            workspace.mkdir()
            (workspace / (name + " 中文.py")).write_text("PRIVATE_BODY_" + name, encoding="utf-8")
            sid = "file-reference-profile-" + name
            await remote.invoke(dict(namespace="session", method="create", args=dict(request=dict(
                sessionId=sid, cwd=str(workspace), agentPreset=preset))))
            agent = ctx.get("agents").get(sid)
            before = copy.deepcopy(agent.session.events)
            assert await remote.invoke(dict(namespace="fileReferences", method="list", args=dict(
                agentId=sid, query=name))) == [dict(path=name + " 中文.py", kind="file")]
            assembly = await ctx.get("systemPrompt").assemble(dict(scope=scope_of(agent.ctx)))
            assert not any("PRIVATE_BODY_" in section["text"] for section in assembly["sections"])
            guidance = next((section["text"] for section in assembly["sections"] if section["name"] == "context:file-reference"), "")
            assert guidance == (FILE_REFERENCE_PROMPT if ctx.get("tools").get("read", agent) else "")
            assert agent.session.events == before
            await ctx.get("sessions").flush(agent.session)
    finally:
        await close_web_context(ctx)
