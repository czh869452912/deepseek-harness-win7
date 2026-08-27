import asyncio
import os
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.tools import ToolExecutionInput, ToolsService
from dsh.fs.tool_fs_search import ToolFsSearchPlugin
from dsh.fs.tool_fs_search.glob import parse_glob_args, sample_across_top_level
from dsh.fs.tool_fs_search.grep import parse_grep_args
from dsh.fs.tool_fs_search.search_core import preview_line
from dsh.spill.spill_store import SpillStore
from dsh.subprocess import LocalSubprocessRuntime, SubprocessCollect


class PromptService:
    def __init__(self):
        self.sections = {}

    def section(self, *args, **kwargs):
        section = args[0] if args and isinstance(args[0], dict) else dict(kwargs)
        self.sections[section["name"]] = section

        def dispose():
            self.sections.pop(section["name"], None)

        return dispose


class FakeOutputReader:
    def __init__(self, text, lossy=False):
        self.text = text
        self.lossy = lossy

    def read_from(self, _offset):
        return SimpleNamespace(text=self.text, lossy=self.lossy, spillPath=None)


class FakeSubprocess:
    def __init__(self, stdout="", stderr="", exit_code=0, process_signal=None,
                 stdout_lossy=False, stderr_lossy=False):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.process_signal = process_signal
        self.stdout_lossy = stdout_lossy
        self.stderr_lossy = stderr_lossy
        self.spawns = []

    def spawn(self, spec):
        self.spawns.append(spec)
        done = asyncio.get_running_loop().create_future()
        done.set_result(SimpleNamespace(exitCode=self.exit_code, signal=self.process_signal))
        return SimpleNamespace(
            done=done,
            collected=SimpleNamespace(
                stdout=FakeOutputReader(self.stdout, self.stdout_lossy),
                stderr=FakeOutputReader(self.stderr, self.stderr_lossy),
            ),
        )


async def mount_fake_search(fake, config=None):
    ctx = Context()
    prompt = PromptService()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.set_service("systemPrompt", prompt)
    ctx.set_service("subprocess", fake)
    resolved_config = {"sampleOverCapGlobResults": True}
    resolved_config.update(config or {})
    fiber = ctx.registry.plugin(ToolFsSearchPlugin, resolved_config, parent_ctx=ctx)
    await fiber
    return ctx, tools, prompt, fiber


async def mount_search(tmp_path, config=None):
    ctx = Context()
    prompt = PromptService()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.set_service("systemPrompt", prompt)
    LocalSubprocessRuntime(ctx)
    resolved_config = {"sampleOverCapGlobResults": True}
    resolved_config.update(config or {})
    fiber = ctx.registry.plugin(ToolFsSearchPlugin, resolved_config, parent_ctx=ctx)
    await fiber
    return ctx, tools, prompt, fiber


def agent_at(path, ctx=None):
    return SimpleNamespace(ctx=ctx, session=SimpleNamespace(header=SimpleNamespace(id="s1", cwd=str(path))))


def scoped_agent(fiber):
    return SimpleNamespace(ctx=fiber.ctx, session=SimpleNamespace(header=SimpleNamespace(id="s1", cwd=os.getcwd())))


def text(result):
    return "".join(block["text"] for block in result.content if block["type"] == "text")


def test_argument_parsers_and_utf8_preview_match_upstream():
    assert parse_glob_args({"pattern": "*.py"}) == {"pattern": "*.py"}
    with pytest.raises(ValueError, match="non-empty"):
        parse_glob_args({"pattern": "  "})
    assert parse_grep_args({"pattern": "  ", "include": "*.{ts,tsx}"})["pattern"] == "  "
    with pytest.raises(ValueError, match="comma-separated"):
        parse_grep_args({"pattern": "x", "include": "*.ts,*.js"})
    assert preview_line("aéz", 3) == "aé (line truncated)"


def test_config_caps_are_positive_integers_and_grace_fits_timer():
    with pytest.raises(ValueError, match="sampleOverCapGlobResults"):
        ToolFsSearchPlugin({})
    with pytest.raises(ValueError, match="sampleOverCapGlobResults"):
        ToolFsSearchPlugin({"sampleOverCapGlobResults": "yes"})
    with pytest.raises(ValueError, match="globMaxResults"):
        ToolFsSearchPlugin({"sampleOverCapGlobResults": True, "globMaxResults": 0})
    with pytest.raises(ValueError, match="grepMaxMatches"):
        ToolFsSearchPlugin({"sampleOverCapGlobResults": True, "grepMaxMatches": 1.5})
    with pytest.raises(ValueError, match="graceMs"):
        ToolFsSearchPlugin({"sampleOverCapGlobResults": True, "graceMs": 2_147_483_648})


def test_top_level_sampling_round_robins_without_reordering_groups():
    sampled = sample_across_top_level(
        ["src/a", "src/b", "packages/a", "docs/a", "packages/b"], 4, "."
    )
    assert sampled == {
        "items": ["src/a", "src/b", "packages/a", "docs/a"],
        "shown": 3,
        "total": 3,
    }


def test_plugin_declares_the_subprocess_seam_not_fs():
    assert ToolFsSearchPlugin.inject == ["tools", "systemPrompt", "subprocess"]


@pytest.mark.asyncio
async def test_glob_spawns_packaged_rg_with_fixed_budgeted_spec(tmp_path):
    fake = FakeSubprocess(stdout="old.ts\nnew.ts\n")
    ctx, tools, _prompt, fiber = await mount_fake_search(fake, {
        "rawOutputMaxBytes": 1234,
        "stderrMaxBytes": 234,
        "graceMs": 345,
    })
    signal = asyncio.Event()
    try:
        result = await tools.execute(ToolExecutionInput(
            "spawn", "glob", {"pattern": "*.ts", "path": "src dir"},
            agent=agent_at(tmp_path, fiber.ctx), signal=signal,
        ))
        assert result.value == {"root": "src dir", "paths": ["old.ts", "new.ts"]}
        spec = fake.spawns[0]
        assert os.path.basename(spec.argv[0]).lower() in ("rg", "rg.exe")
        assert spec.argv[1:] == [
            "--no-config", "--files", "--glob=*.ts", "--sort=modified",
            "--no-ignore", "--hidden",
            "--glob=!**/.git", "--glob=!**/.git/**",
            "--glob=!**/.svn", "--glob=!**/.svn/**",
            "--glob=!**/.hg", "--glob=!**/.hg/**",
            "--glob=!**/.bzr", "--glob=!**/.bzr/**",
            "--glob=!**/.jj", "--glob=!**/.jj/**",
            "--glob=!**/.sl", "--glob=!**/.sl/**",
            "--", "src dir",
        ]
        assert spec.cwd == str(tmp_path)
        assert spec.signal is signal
        assert spec.graceMs == 345
        assert spec.stdio.stdin == "ignore"
        assert isinstance(spec.stdio.stdout, SubprocessCollect)
        assert spec.stdio.stdout.maxBytes == 1234
        assert isinstance(spec.stdio.stderr, SubprocessCollect)
        assert spec.stdio.stderr.maxBytes == 234
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_grep_parses_only_match_framing_and_preserves_non_utf8_placeholder(tmp_path):
    records = [
        {"type": "begin", "data": {"path": {"text": "a.txt"}}},
        {"type": "match", "data": {
            "path": {"text": str(tmp_path / "a.txt")},
            "line_number": 2,
            "lines": {"text": "hello\r\n"},
        }},
        {"type": "match", "data": {
            "path": {"text": "bad.bin"},
            "line_number": 4,
            "lines": {"bytes": "//4="},
        }},
        {"type": "summary", "data": {}},
    ]
    stdout = "\n".join(__import__("json").dumps(record) for record in records) + "\n"
    fake = FakeSubprocess(stdout=stdout)
    _ctx, tools, _prompt, fiber = await mount_fake_search(fake)
    try:
        result = await tools.execute(ToolExecutionInput(
            "json", "grep", {"pattern": "hello"},
            agent=agent_at(tmp_path, fiber.ctx), signal=asyncio.Event(),
        ))
        assert result.value == {"matches": [
            {"path": "a.txt", "lineNumber": 2, "line": "hello"},
            {"path": "bad.bin", "lineNumber": 4, "line": "(line is not valid UTF-8)"},
        ]}
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fake, expected_code", [
    (FakeSubprocess(stderr="regex parse error: bad", exit_code=2), "SEARCH_INVALID_PATTERN"),
    (FakeSubprocess(stdout="partial", stdout_lossy=True), "SEARCH_RAW_OUTPUT_OVERFLOW"),
    (FakeSubprocess(process_signal="SIGTERM", exit_code=None), "SEARCH_FAILED"),
])
async def test_subprocess_failures_keep_the_search_error_vocabulary(fake, expected_code):
    _ctx, tools, _prompt, fiber = await mount_fake_search(fake)
    try:
        result = await tools.execute(ToolExecutionInput(
            "failure", "grep", {"pattern": "x"}, agent=scoped_agent(fiber), signal=asyncio.Event(),
        ))
        assert result.is_error
        assert result.error["info"]["code"] == expected_code
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_abort_observed_after_spawn_is_search_aborted():
    signal = asyncio.Event()

    class AbortDuringSpawn(FakeSubprocess):
        def spawn(self, spec):
            handle = super().spawn(spec)
            signal.set()
            return handle

    fake = AbortDuringSpawn()
    _ctx, tools, _prompt, fiber = await mount_fake_search(fake)
    try:
        result = await tools.execute(ToolExecutionInput(
            "abort", "glob", {"pattern": "*"}, agent=scoped_agent(fiber), signal=signal,
        ))
        assert result.is_error
        assert result.error["info"]["code"] == "SEARCH_ABORTED"
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_no_session_uses_process_cwd_and_absolute_root_is_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    absolute_root = str(tmp_path / "src")
    fake = FakeSubprocess(stdout=str(tmp_path / "src" / "a.ts") + "\n")
    _ctx, tools, _prompt, fiber = await mount_fake_search(fake)
    try:
        result = await tools.execute(ToolExecutionInput(
            "cwd", "glob", {"pattern": "*.ts", "path": absolute_root},
            agent=SimpleNamespace(ctx=fiber.ctx), signal=asyncio.Event(),
        ))
        assert fake.spawns[0].cwd == str(tmp_path)
        assert result.value == {
            "root": "src",
            "paths": [os.path.join("src", "a.ts")],
        }
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_registers_canonical_tools_prompt_sections_and_disposes(tmp_path):
    ctx, tools, prompt, fiber = await mount_search(tmp_path)
    try:
        assert set(prompt.sections) == {"tool:glob", "tool:grep"}
        glob = tools.get_tool("glob", fiber.ctx)
        grep = tools.get_tool("grep", fiber.ctx)
        assert glob is not None and glob.canonical and glob.timeout_ms == 30000
        assert grep is not None and grep.canonical and grep.timeout_ms == 30000
        assert glob.output["schema"]["required"] == ["root", "paths"]
        assert grep.output["schema"]["required"] == ["matches"]
    finally:
        await fiber.dispose()
    assert tools.get_tool("glob", fiber.ctx) is None
    assert tools.get_tool("grep", fiber.ctx) is None
    assert prompt.sections == {}


@pytest.mark.asyncio
async def test_glob_prompt_and_description_follow_disabled_sampling_cap():
    fake = FakeSubprocess(stdout="")
    _ctx, tools, prompt, fiber = await mount_fake_search(fake, {
        "sampleOverCapGlobResults": False,
        "globMaxResults": 7,
    })
    try:
        prompt_text = prompt.sections["tool:glob"]["text"]
        description = tools.get("glob", fiber.ctx).description
        assert "keeps the modification-time-ordered head" in prompt_text
        assert "sampled across top-level entries" not in prompt_text
        assert "returns the first 7 paths in modification-time order" in description
        assert "does not enumerate directory entries" in description
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_glob_uses_session_cwd_hidden_vcs_sort_and_complete_value(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "old.ts").write_text("old", encoding="utf-8")
    (tmp_path / "src" / "new.ts").write_text("new", encoding="utf-8")
    (tmp_path / ".hidden.ts").write_text("hidden", encoding="utf-8")
    (tmp_path / ".git" / "config.ts").write_text("vcs", encoding="utf-8")
    os.utime(str(tmp_path / "src" / "old.ts"), (946684800, 946684800))
    os.utime(str(tmp_path / "src" / "new.ts"), (1577836800, 1577836800))
    ctx, tools, _prompt, fiber = await mount_search(
        tmp_path, {"sampleOverCapGlobResults": False, "globMaxResults": 2}
    )
    try:
        result = await tools.execute(ToolExecutionInput(
            "g1", "glob", {"pattern": "**/*.ts"}, agent=agent_at(tmp_path, fiber.ctx), signal=asyncio.Event()
        ))
        assert not result.is_error
        assert len(result.value["paths"]) == 3
        old_path = os.path.join("src", "old.ts")
        new_path = os.path.join("src", "new.ts")
        assert result.value["paths"].index(old_path) < result.value["paths"].index(new_path)
        assert ".hidden.ts" in result.value["paths"]
        assert os.path.join(".git", "config.ts") not in result.value["paths"]
        assert "Showing 2 of 3 paths" in text(result)
        assert result.meta["shape"] == "paths"
        assert result.meta["truncated"] is True and result.meta["total"] == 3
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_grep_regex_case_include_full_value_preview_without_fs_observation(tmp_path):
    (tmp_path / "a.ts").write_text("Alpha\nalpha éé tail\n", encoding="utf-8")
    (tmp_path / "b.tsx").write_text("alpha two\nalpha three\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("alpha ignored\n", encoding="utf-8")
    observed = []
    ctx, tools, _prompt, fiber = await mount_search(
        tmp_path, {"sampleOverCapGlobResults": True, "grepMaxMatches": 2, "grepMaxLineBytes": 8}
    )
    ctx.on("fs/observed", lambda *args: observed.append(args), global_listener=True)
    try:
        result = await tools.execute(ToolExecutionInput(
            "r1", "grep", {"pattern": "alpha", "include": "*.{ts,tsx}"},
            agent=agent_at(tmp_path, fiber.ctx), signal=asyncio.Event()
        ))
        assert not result.is_error
        assert len(result.value["matches"]) == 3
        assert all(match["path"] != "c.md" for match in result.value["matches"])
        assert "Alpha" not in text(result)
        assert "(line truncated)" in text(result)
        assert result.meta["truncated"] is True and result.meta["total"] == 3
        view = tools.get_tool("grep", fiber.ctx).present_result(
            {"pattern": "alpha", "include": "*.{ts,tsx}"}, result
        )
        assert view["card"] == "search" and view["shape"] == "matches"
        assert observed == []
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_glob_does_not_follow_symlinks_and_spills_complete_sorted_result(tmp_path):
    (tmp_path / "real").mkdir()
    for name in ("a.ts", "b.ts", "c.ts"):
        (tmp_path / "real" / name).write_text(name, encoding="utf-8")
    link = tmp_path / "linked"
    try:
        os.symlink(str(tmp_path / "real"), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks require a Windows privilege not available here")
    ctx, tools, _prompt, fiber = await mount_search(
        tmp_path, {"sampleOverCapGlobResults": False, "globMaxResults": 1}
    )
    store = SpillStore(root=str(tmp_path / "spill"))
    ctx.set_service("spillStore", store)
    try:
        result = await tools.execute(ToolExecutionInput(
            "spill", "glob", {"pattern": "*.ts"}, agent=agent_at(tmp_path, fiber.ctx), signal=asyncio.Event()
        ))
        assert len(result.value["paths"]) == 3
        assert all(not path.startswith("linked" + os.sep) for path in result.value["paths"])
        assert "Full sorted result stored at:" in text(result)
        spill_path = text(result).split("Full sorted result stored at: ", 1)[1].split(". Read with", 1)[0]
        with open(spill_path, "r", encoding="utf-8") as handle:
            assert handle.read().splitlines() == list(result.value["paths"])
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_shadowed_glob_does_not_trigger_the_fs_search_spill_hook(tmp_path):
    fake = FakeSubprocess()
    ctx, tools, _prompt, fiber = await mount_fake_search(
        fake, {"globMaxResults": 1}
    )
    saves = []

    class Spill:
        async def saveText(self, request):
            saves.append(request)
            return {"locator": "unexpected", "retrievalHint": "unexpected"}

    ctx.set_service("spillStore", Spill())
    shadow_contexts = []

    class ShadowPlugin:
        inject = ["tools"]

        def apply(self, child):
            shadow_contexts.append(child)
            child.tools.register({
                "name": "glob",
                "description": "shadow glob",
                "parameters": {
                    "type": "object", "additionalProperties": False,
                    "required": ["pattern"],
                    "properties": {"pattern": {"type": "string"}},
                },
                "output": {
                    "schema": {
                        "type": "object", "additionalProperties": False,
                        "required": ["root", "paths"],
                        "properties": {
                            "root": {"type": "string"},
                            "paths": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "render": lambda _args, value: [{"type": "text", "text": "shadow"}],
                },
                "execute": lambda _args, _exec: {"root": ".", "paths": ["a", "b"]},
            })

    shadow = ctx.registry.plugin(ShadowPlugin(), parent_ctx=ctx.extend())
    await shadow
    agent = agent_at(tmp_path)
    agent.ctx = shadow_contexts[0]
    try:
        result = await tools.execute(ToolExecutionInput(
            "shadow", "glob", {"pattern": "*"}, agent=agent, signal=asyncio.Event()
        ))
        assert not result.is_error
        assert result.value["paths"] == ["a", "b"]
        assert saves == []
        assert fake.spawns == []
    finally:
        await shadow.dispose()
        await fiber.dispose()


@pytest.mark.asyncio
async def test_search_errors_are_typed_and_preaborted_is_registry_owned(tmp_path):
    ctx, tools, _prompt, fiber = await mount_search(tmp_path)
    try:
        invalid = await tools.execute(ToolExecutionInput(
            "bad", "grep", {"pattern": "(unclosed"}, agent=scoped_agent(fiber), signal=asyncio.Event()
        ))
        assert invalid.is_error and invalid.error["info"]["code"] == "SEARCH_INVALID_PATTERN"
        lookahead = await tools.execute(ToolExecutionInput(
            "lookahead", "grep", {"pattern": "(?=x)x"}, agent=scoped_agent(fiber), signal=asyncio.Event()
        ))
        assert lookahead.is_error and lookahead.error["info"]["code"] == "SEARCH_INVALID_PATTERN"
        bad_glob = await tools.execute(ToolExecutionInput(
            "bad-glob", "glob", {"pattern": "[z-a]"}, agent=scoped_agent(fiber), signal=asyncio.Event()
        ))
        assert bad_glob.is_error and bad_glob.error["info"]["code"] == "SEARCH_INVALID_PATTERN"
        missing = await tools.execute(ToolExecutionInput(
            "missing", "glob", {"pattern": "*", "path": "gone"},
            agent=agent_at(tmp_path, fiber.ctx), signal=asyncio.Event()
        ))
        assert missing.is_error and missing.error["info"]["code"] == "SEARCH_FAILED"
        signal = asyncio.Event()
        signal.set()
        aborted = await tools.execute(ToolExecutionInput(
            "stop", "grep", {"pattern": "x"}, agent=scoped_agent(fiber), signal=signal
        ))
        assert aborted.error["info"]["code"] == "ABORTED_BEFORE_DISPATCH"
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_grep_honors_gitignore(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("needle\n", encoding="utf-8")
    _ctx, tools, _prompt, fiber = await mount_search(tmp_path)
    try:
        result = await tools.execute(ToolExecutionInput(
            "ignore", "grep", {"pattern": "needle"},
            agent=agent_at(tmp_path, fiber.ctx), signal=asyncio.Event(),
        ))
        assert [match["path"] for match in result.value["matches"]] == ["visible.txt"]
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_raw_output_budget_fails_instead_of_returning_partial_value(tmp_path):
    (tmp_path / "long-name.ts").write_text("needle\n", encoding="utf-8")
    ctx, tools, _prompt, fiber = await mount_search(
        tmp_path, {"sampleOverCapGlobResults": True, "rawOutputMaxBytes": 1}
    )
    try:
        result = await tools.execute(ToolExecutionInput(
            "raw", "glob", {"pattern": "*.ts"}, agent=agent_at(tmp_path, fiber.ctx), signal=asyncio.Event()
        ))
        assert result.is_error
        assert result.error["info"]["code"] == "SEARCH_RAW_OUTPUT_OVERFLOW"
        assert result.value is None
    finally:
        await fiber.dispose()
