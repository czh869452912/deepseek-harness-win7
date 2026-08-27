import asyncio
import os

import pytest

from dsh.cordis.events import EventBus
from dsh.core.tools import ToolExecutionInput, ToolRunContext, ToolsService
from dsh.fs.fs_local import FsError, FsService, FsTarget
from dsh.fs.tool_str_replace_editor import (
    DEFAULT_DESCRIPTION,
    TRUNCATED_MESSAGE,
    StrReplaceEditorPlugin,
)


class DirectContext:
    def __init__(self, cwd):
        self.events = EventBus()
        self.services = {"fs": FsService(cwd=str(cwd))}
        self.effects = []
        self.tools = ToolsService(self)
        self.services["tools"] = self.tools

    def get(self, name):
        return self.services[name]

    def has(self, name):
        return name in self.services

    def on(self, event, handler):
        return self.events.on(event, handler)

    async def waterfall(self, event, data, *args):
        return await self.events.waterfall(event, data, *args)

    def emit(self, event, *args):
        self.events.emit(event, *args)

    def effect(self, disposer, label=""):
        cleanup = disposer()
        if cleanup is not None:
            self.effects.append(cleanup)

    def dispose(self):
        while self.effects:
            self.effects.pop()()


async def invoke(tools, ctx, arguments, signal=None, agent=None):
    caller_signal = signal if signal is not None else asyncio.Event()
    execution = ToolRunContext(ToolExecutionInput(
        "call-editor",
        "str_replace_editor",
        arguments,
        agent=agent,
        signal=caller_signal,
    ))
    return await tools.get_tool("str_replace_editor").execute(arguments, execution, ctx)


@pytest.fixture
def editor(tmp_path):
    ctx = DirectContext(tmp_path)
    tools = ctx.tools
    plugin = StrReplaceEditorPlugin()
    plugin.apply(ctx)
    return ctx, tools, plugin


@pytest.mark.asyncio
async def test_create_waterfall_receives_target_actor_and_forwarding_default(editor, tmp_path):
    ctx, tools, _ = editor
    seen = []

    async def decide(target, actor, next_fn):
        seen.append((target, actor))
        return await next_fn()

    ctx.on("fs/write-intent", decide)
    path = str(tmp_path / "created.txt")
    result = await invoke(tools, ctx, {"command": "create", "path": path, "file_text": "fresh"})

    assert result == "New file created successfully at: " + os.path.abspath(path)
    assert len(seen) == 1
    assert isinstance(seen[0][0], FsTarget)
    assert seen[0][0].displayPath == os.path.abspath(path)
    assert isinstance(seen[0][1], ToolRunContext)


@pytest.mark.asyncio
async def test_tool_run_context_signal_reaches_every_filesystem_boundary(editor, tmp_path):
    ctx, tools, _ = editor
    signal = asyncio.Event()
    signal.set()

    with pytest.raises(FsError) as aborted:
        await invoke(
            tools,
            ctx,
            {"command": "view", "path": str(tmp_path / "missing.txt")},
            signal=signal,
        )
    assert aborted.value.code == "FS_ABORTED"


@pytest.mark.asyncio
async def test_same_caller_signal_is_forwarded_to_all_fs_operations(editor, tmp_path, monkeypatch):
    ctx, tools, _ = editor
    fs = ctx.get("fs")
    signal = asyncio.Event()
    seen = []

    original_resolve = fs.resolve
    original_stat = fs.stat
    original_read = fs.readText
    original_list = fs.listDir
    original_write = fs.writeText

    async def resolve(path, opts=None):
        seen.append(("resolve", opts.get("signal") if opts else None))
        return await original_resolve(path, opts)

    async def stat(target, operation_signal=None):
        seen.append(("stat", operation_signal))
        return await original_stat(target, operation_signal)

    async def read_text(target, operation_signal=None):
        seen.append(("readText", operation_signal))
        return await original_read(target, operation_signal)

    async def list_dir(target, operation_signal=None):
        seen.append(("listDir", operation_signal))
        return await original_list(target, operation_signal)

    async def write_text(target, content, expected=None, operation_signal=None,
                         sandbox_policy=None):
        seen.append(("writeText", operation_signal))
        return await original_write(target, content, expected, operation_signal, sandbox_policy)

    monkeypatch.setattr(fs, "resolve", resolve)
    monkeypatch.setattr(fs, "stat", stat)
    monkeypatch.setattr(fs, "readText", read_text)
    monkeypatch.setattr(fs, "listDir", list_dir)
    monkeypatch.setattr(fs, "writeText", write_text)

    path = str(tmp_path / "signal.txt")
    await invoke(tools, ctx, {"command": "create", "path": path, "file_text": "old"}, signal=signal)
    await invoke(tools, ctx, {"command": "view", "path": path}, signal=signal)
    await invoke(
        tools,
        ctx,
        {"command": "str_replace", "path": path, "old_str": "old", "new_str": "new"},
        signal=signal,
    )
    await invoke(tools, ctx, {"command": "view", "path": str(tmp_path)}, signal=signal)

    assert {operation for operation, _ in seen} == {
        "resolve", "stat", "readText", "listDir", "writeText",
    }
    assert all(operation_signal is signal for _, operation_signal in seen)


@pytest.mark.asyncio
async def test_edit_waterfall_intent_controls_expected_version(editor, tmp_path):
    ctx, tools, _ = editor
    path = tmp_path / "edit.txt"
    path.write_text("old", encoding="utf-8")

    async def observed_version(target, actor, next_fn):
        assert isinstance(target, FsTarget)
        assert isinstance(actor, ToolRunContext)
        return {"version": "stale-version"}

    ctx.on("fs/edit-intent", observed_version)
    with pytest.raises(FsError, match="file changed since it was read"):
        await invoke(tools, ctx, {"command": "str_replace", "path": str(path), "old_str": "old", "new_str": "new"})
    assert path.read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_canonical_file_operations_and_literal_replacement(editor, tmp_path):
    ctx, tools, _ = editor
    path = tmp_path / "sample.txt"
    replacement = "$&|$`|$'|$$"

    assert await invoke(tools, ctx, {"command": "create", "path": str(path), "file_text": "one\ntwo\nthree\n"}) == "New file created successfully at: " + os.path.abspath(str(path))
    view = await invoke(tools, ctx, {"command": "view", "path": str(path), "view_range": [2, -1]})
    assert view == "\n".join([
        "Here's the content of %s with line numbers (which has a total of 4 lines) with view_range=[2, -1]:" % os.path.abspath(str(path)),
        "     2  two", "     3  three", "     4  ", "",
    ])
    await invoke(tools, ctx, {"command": "str_replace", "path": str(path), "old_str": "two", "new_str": replacement})
    await invoke(tools, ctx, {"command": "insert", "path": str(path), "insert_line": 1, "new_str": "between"})
    assert path.read_text(encoding="utf-8") == "one\nbetween\n%s\nthree\n" % replacement


@pytest.mark.asyncio
async def test_directory_listing_filters_depth_sorts_and_clips(editor, tmp_path):
    ctx, tools, _ = editor
    root = tmp_path / "dir"
    (root / "nested" / "third").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / "nested" / "child.txt").write_text("child", encoding="utf-8")
    (root / "nested" / "third" / "too-deep.txt").write_text("deep", encoding="utf-8")
    (root / "visible.txt").write_text("ok", encoding="utf-8")
    (root / ".hidden").write_text("hidden", encoding="utf-8")

    listing = await invoke(tools, ctx, {"command": "view", "path": str(root)})
    assert ".hidden" not in listing
    assert "too-deep.txt" not in listing
    assert "child.txt" in listing
    rows = [line for line in listing.splitlines() if "\t" in line]
    assert not any("node_modules" in row for row in rows)
    assert not any("__pycache__" in row for row in rows)
    assert rows == sorted(rows, key=lambda row: row.split("\t", 1)[1])

    clipped_ctx = DirectContext(tmp_path)
    clipped_tools = clipped_ctx.tools
    StrReplaceEditorPlugin({"maxOutputChars": 10}).apply(clipped_ctx)
    large = tmp_path / "large.txt"
    large.write_text("x" * 100, encoding="utf-8")
    clipped = await invoke(clipped_tools, clipped_ctx, {"command": "view", "path": str(large)})
    assert TRUNCATED_MESSAGE in clipped


@pytest.mark.asyncio
async def test_errors_are_typed_and_match_upstream(editor, tmp_path):
    ctx, _, plugin = editor
    missing = str(tmp_path / "missing.txt")
    with pytest.raises(FsError) as absent:
        await plugin.handle_editor("view", missing, ctx=ctx)
    assert absent.value.code == "FS_NOT_FOUND"
    assert str(absent.value) == "The path %s does not exist. Please provide a valid path." % os.path.abspath(missing)

    ambiguous = tmp_path / "ambiguous.txt"
    ambiguous.write_text("same\nother\nsame", encoding="utf-8")
    with pytest.raises(FsError) as repeated:
        await plugin.handle_editor("str_replace", str(ambiguous), old_str="same", new_str="x", ctx=ctx)
    assert repeated.value.code == "FS_AMBIGUOUS_EDIT"
    assert "Multiple occurrences of old_str `same` in lines [1, 3]" in str(repeated.value)

    with pytest.raises(ValueError, match="path must be a non-empty string"):
        await plugin.handle_editor("view", "", ctx=ctx)
    with pytest.raises(ValueError, match="is not an absolute path"):
        await plugin.handle_editor("view", "relative.txt", ctx=ctx)


def test_schema_config_presentation_and_effect_disposal(tmp_path):
    ctx = DirectContext(tmp_path)
    tools = ctx.tools
    plugin = StrReplaceEditorPlugin({"description": "custom", "maxOutputChars": 20})
    plugin.apply(ctx)
    tool = tools.get_tool("str_replace_editor")

    assert plugin.inject == ["tools", "fs"]
    assert tool.description == "custom"
    assert tool.parameters["required"] == ["command", "path"]
    assert tool.output["schema"] == {"type": "string"}
    assert tool.output["render"]({}, "result") == [{"type": "text", "text": "result"}]
    assert tool.present_call({"command": "insert", "path": "/a", "insert_line": 0})["locations"] == [{"path": "/a", "line": 1}]
    assert tool.present_call({"command": "str_replace", "path": "/a"})["diffs"] == [
        {"path": "/a", "oldText": None, "newText": ""},
    ]
    assert DEFAULT_DESCRIPTION.startswith("Custom editing tool")

    ctx.dispose()
    assert tools.get_tool("str_replace_editor") is None

    with pytest.raises(ValueError, match="maxOutputChars must be a positive safe integer"):
        StrReplaceEditorPlugin({"maxOutputChars": 0})
    with pytest.raises(ValueError, match="description must be non-empty"):
        StrReplaceEditorPlugin({"description": " "})


@pytest.mark.asyncio
async def test_sandbox_denial_is_mapped_with_resolved_mode(tmp_path):
    class DenyingFs(FsService):
        @property
        def sandboxMode(self):
            return "read-only"

        async def writeText(self, target, content, expected=None, signal=None, sandbox_policy=None):
            assert sandbox_policy == {"mode": "read-only"}
            raise FsError("backend denied", "FS_SANDBOX_DENIED")

    session = object()

    class Agent:
        def __init__(self):
            self.session = session

    class Policy:
        requests = []

        def resolve(self, request):
            assert request == {"session": session}
            self.requests.append(request)
            return {"mode": "read-only"}

    ctx = DirectContext(tmp_path)
    ctx.services["fs"] = DenyingFs(cwd=str(tmp_path))
    ctx.services["sandboxPolicy"] = Policy()
    StrReplaceEditorPlugin().apply(ctx)

    with pytest.raises(FsError) as denied:
        await invoke(
            ctx.tools,
            ctx,
            {
                "command": "create",
                "path": str(tmp_path / "blocked.txt"),
                "file_text": "blocked",
            },
            agent=Agent(),
        )
    assert denied.value.code == "FS_SANDBOX_DENIED"
    assert str(denied.value) == "[sandbox: file access denied under read-only mode]"

    existing = tmp_path / "existing.txt"
    existing.write_text("old", encoding="utf-8")
    for arguments in (
        {"command": "str_replace", "path": str(existing), "old_str": "old", "new_str": "new"},
        {"command": "insert", "path": str(existing), "insert_line": 1, "new_str": "new"},
    ):
        with pytest.raises(FsError) as mutation_denied:
            await invoke(ctx.tools, ctx, arguments, agent=Agent())
        assert mutation_denied.value.code == "FS_SANDBOX_DENIED"
    assert len(ctx.services["sandboxPolicy"].requests) == 3
