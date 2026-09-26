"""
1:1 parity suite for the filesystem tools under the default deployment, where
`@deepseek-ai/dsh-fs-observation-policy` (`dsh/fs/fs_observation_policy.py`)
supplies the prior-observation guard.

Upstream is reference/packages/fs/tool-fs/tests/integration.spec.ts: the
observed-state record decides whether a write may replace and whether an edit
has a version basis, and the provider performs the atomic freshness/no-clobber
check. Assertions read files back byte-for-byte rather than trusting tool
messages, exactly as upstream does.

Upstream cases in that suite this port cannot carry yet are the `read` rendering
('returns line-numbered content', 'paginates a multi-line file with offset/limit'),
the binary-file read error, the model-facing remedy suffix, and the tool stat
budget: the port's `read` rendering, remediation text, and stat placement belong
to the `dsh-tool-fs` row's own migration unit, not to the policy provider.
"""

import contextlib
import os
import shutil
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from dsh.core.tools import ToolsService
from dsh.cordis.context import Context
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.fs_observation_policy import FsObservationPolicyPlugin
from dsh.fs.tool_fs import ToolFsPlugin


class _SessionObject:
    """The opaque session identity the policy's owner map weakly keys on."""


class Harness:
    """The default deployment: tools + local fs + the observation policy."""

    def __init__(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="dsh-tool-fs-")
        self.ctx = Context()
        self.calls = 0
        self.agent = SimpleNamespace(session=_SessionObject())
        self.fiber: Any = None

    async def boot(self, with_policy: bool = True) -> None:
        self.ctx.set_service("tools", ToolsService(self.ctx))
        await self.ctx.plugin(FsLocalPlugin, {"cwd": self.dir})
        if with_policy:
            await self.ctx.plugin(FsObservationPolicyPlugin)
        self.fiber = await self.ctx.plugin(ToolFsPlugin)

    async def dispose(self) -> None:
        if self.fiber is not None:
            await self.fiber.dispose()
            self.fiber = None
        shutil.rmtree(self.dir, ignore_errors=True)

    async def call(self, name: str, args: Dict[str, Any]) -> Any:
        self.calls += 1
        return await self.ctx.get("tools").execute(
            {
                "signal": None,
                "callId": "call-{}".format(self.calls),
                "name": name,
                "arguments": args,
                "agent": self.agent,
            }
        )

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def read_disk(self, name: str) -> str:
        with open(self.path(name), encoding="utf-8") as handle:
            return handle.read()

    def write_disk(self, name: str, content: str) -> None:
        with open(self.path(name), "w", encoding="utf-8") as handle:
            handle.write(content)


@contextlib.asynccontextmanager
async def deployment(with_policy: bool = True):
    """The default deployment (policy mounted), or the bare provider one."""
    harness = Harness()
    await harness.boot(with_policy)
    try:
        yield harness
    finally:
        await harness.dispose()


def text(result: Any) -> str:
    return "".join(block.get("text", "") for block in result.content if block.get("type") == "text")


def code(result: Any) -> Optional[str]:
    error = result.error
    if not isinstance(error, dict):
        return None
    info = error.get("info")
    return info.get("code") if isinstance(info, dict) else None


# --- write -> disk -----------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_a_file_with_exactly_the_requested_bytes():
    async with deployment() as h:
        result = await h.call("write", {"file_path": "new.txt", "content": "line one\nline two\n"})
        assert result.is_error is False
        assert h.read_disk("new.txt") == "line one\nline two\n"


@pytest.mark.asyncio
async def test_rejects_overwriting_an_existing_file_without_reading_it_first():
    async with deployment() as h:
        h.write_disk("a.txt", "original")
        result = await h.call("write", {"file_path": "a.txt", "content": "clobber"})
        assert result.is_error is True
        assert code(result) == "FS_NOT_OBSERVED"
        assert h.read_disk("a.txt") == "original"


@pytest.mark.asyncio
async def test_allows_overwriting_after_a_read():
    async with deployment() as h:
        h.write_disk("a.txt", "original")
        assert (await h.call("read", {"file_path": "a.txt"})).is_error is False
        result = await h.call("write", {"file_path": "a.txt", "content": "replaced"})
        assert result.is_error is False
        assert h.read_disk("a.txt") == "replaced"


@pytest.mark.asyncio
async def test_rejects_a_full_overwrite_when_the_file_changed_since_the_read():
    async with deployment() as h:
        h.write_disk("a.txt", "original")
        await h.call("read", {"file_path": "a.txt"})
        h.write_disk("a.txt", "changed-externally")  # out-of-band change
        result = await h.call("write", {"file_path": "a.txt", "content": "replaced"})
        assert result.is_error is True
        assert code(result) == "FS_STALE_VERSION"
        assert "file changed since it was read" in text(result)


@pytest.mark.asyncio
async def test_the_stale_remedy_is_actionable_for_a_write():
    async with deployment() as h:
        h.write_disk("a.txt", "original")
        await h.call("read", {"file_path": "a.txt"})
        h.write_disk("a.txt", "changed-externally")
        stale = await h.call("write", {"file_path": "a.txt", "content": "replaced"})
        assert stale.is_error is True
        assert code(stale) == "FS_STALE_VERSION"
        # Follow the remedy: re-read (refreshes the observed version), then retry.
        assert (await h.call("read", {"file_path": "a.txt"})).is_error is False
        retried = await h.call("write", {"file_path": "a.txt", "content": "replaced"})
        assert retried.is_error is False
        assert h.read_disk("a.txt") == "replaced"


# --- edit -> disk ------------------------------------------------------------


@pytest.mark.asyncio
async def test_applies_a_unique_literal_replacement_after_a_read():
    async with deployment() as h:
        h.write_disk("a.txt", "hello world")
        await h.call("read", {"file_path": "a.txt"})
        result = await h.call("edit", {"file_path": "a.txt", "old_string": "world", "new_string": "there"})
        assert result.is_error is False
        assert h.read_disk("a.txt") == "hello there"


@pytest.mark.asyncio
async def test_rejects_an_edit_before_any_read_leaving_the_file_untouched():
    async with deployment() as h:
        h.write_disk("a.txt", "hello world")
        result = await h.call("edit", {"file_path": "a.txt", "old_string": "world", "new_string": "there"})
        assert result.is_error is True
        assert code(result) == "FS_NOT_OBSERVED"
        assert "edit requires reading" in text(result)
        assert h.read_disk("a.txt") == "hello world"


@pytest.mark.asyncio
async def test_rejects_an_edit_when_the_file_changed_since_the_windowed_read():
    async with deployment() as h:
        h.write_disk("a.txt", "hello world")
        await h.call("read", {"file_path": "a.txt", "offset": 1, "limit": 1})
        h.write_disk("a.txt", "goodbye")  # out-of-band change removes 'world'
        result = await h.call("edit", {"file_path": "a.txt", "old_string": "world", "new_string": "there"})
        assert result.is_error is True
        assert code(result) == "FS_STALE_VERSION"
        assert "file changed since it was read" in text(result)


@pytest.mark.asyncio
async def test_the_stale_remedy_is_actionable_for_an_edit():
    async with deployment() as h:
        h.write_disk("a.txt", "hello world")
        await h.call("read", {"file_path": "a.txt"})
        h.write_disk("a.txt", "hello brave world")
        stale = await h.call("edit", {"file_path": "a.txt", "old_string": "world", "new_string": "there"})
        assert stale.is_error is True
        assert code(stale) == "FS_STALE_VERSION"
        assert (await h.call("read", {"file_path": "a.txt"})).is_error is False
        retried = await h.call("edit", {"file_path": "a.txt", "old_string": "world", "new_string": "there"})
        assert retried.is_error is False
        assert h.read_disk("a.txt") == "hello brave there"


@pytest.mark.asyncio
async def test_rejects_an_ambiguous_match_without_replace_all():
    async with deployment() as h:
        h.write_disk("a.txt", "a a a")
        await h.call("read", {"file_path": "a.txt"})
        result = await h.call("edit", {"file_path": "a.txt", "old_string": "a", "new_string": "b"})
        assert result.is_error is True
        assert code(result) == "FS_AMBIGUOUS_EDIT"
        assert h.read_disk("a.txt") == "a a a"


@pytest.mark.asyncio
async def test_replaces_all_matches_with_replace_all():
    async with deployment() as h:
        h.write_disk("a.txt", "a a a")
        await h.call("read", {"file_path": "a.txt"})
        result = await h.call(
            "edit", {"file_path": "a.txt", "old_string": "a", "new_string": "b", "replace_all": True}
        )
        assert result.is_error is False
        assert h.read_disk("a.txt") == "b b b"


@pytest.mark.asyncio
async def test_supports_a_full_write_to_edit_cycle_without_an_intervening_read():
    async with deployment() as h:
        await h.call("write", {"file_path": "a.txt", "content": "one two"})
        result = await h.call("edit", {"file_path": "a.txt", "old_string": "two", "new_string": "three"})
        assert result.is_error is False
        assert h.read_disk("a.txt") == "one three"


# --- the gate records only through the events --------------------------------


@pytest.mark.asyncio
async def test_a_direct_filesystem_read_records_no_observed_state_so_a_later_edit_rejects():
    async with deployment() as h:
        h.write_disk("a.txt", "hello world")
        # Reach AROUND the tool - an explicit escape hatch for non-tool consumers.
        await h.ctx.get("fs").readText(await h.ctx.get("fs").resolve("a.txt"))
        # The model-facing edit still rejects: the read did not emit fs/observed.
        result = await h.call("edit", {"file_path": "a.txt", "old_string": "world", "new_string": "there"})
        assert result.is_error is True
        assert code(result) == "FS_NOT_OBSERVED"


# --- deleted observed target -------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_reread_records_absence_so_write_can_safely_recreate_the_file():
    async with deployment() as h:
        h.write_disk("a.txt", "original")
        await h.call("read", {"file_path": "a.txt"})
        os.remove(h.path("a.txt"))  # out-of-band deletion

        # The original positive observation still protects the first mutation.
        edit = await h.call("edit", {"file_path": "a.txt", "old_string": "original", "new_string": "x"})
        assert edit.is_error is True
        assert code(edit) == "FS_STALE_VERSION"
        write = await h.call("write", {"file_path": "a.txt", "content": "premature"})
        assert write.is_error is True
        assert code(write) == "FS_STALE_VERSION"

        # A read-not-found is an authoritative negative observation for this owner.
        reread = await h.call("read", {"file_path": "a.txt"})
        assert reread.is_error is True
        assert code(reread) == "FS_NOT_FOUND"

        # Absence never authorizes edit: there is no content/version to edit.
        retried_edit = await h.call("edit", {"file_path": "a.txt", "old_string": "original", "new_string": "x"})
        assert retried_edit.is_error is True
        assert code(retried_edit) == "FS_NOT_FOUND"

        # The retried write uses createIfAbsent.
        recovered = await h.call("write", {"file_path": "a.txt", "content": "fresh"})
        assert recovered.is_error is False
        assert h.read_disk("a.txt") == "fresh"


# --- bare provider (no dsh-fs-observation-policy) ----------------------------


@pytest.mark.asyncio
async def test_bare_provider_write_unconditionally_creates_a_new_file():
    async with deployment(False) as h:
        result = await h.call("write", {"file_path": "new.txt", "content": "fresh"})
        assert result.is_error is False
        assert h.read_disk("new.txt") == "fresh"


@pytest.mark.asyncio
async def test_bare_provider_write_unconditionally_overwrites_an_existing_unread_file():
    async with deployment(False) as h:
        h.write_disk("a.txt", "original")
        result = await h.call("write", {"file_path": "a.txt", "content": "clobber"})
        assert result.is_error is False
        assert h.read_disk("a.txt") == "clobber"


@pytest.mark.asyncio
async def test_bare_provider_edit_unconditionally_edits_an_unread_existing_file():
    async with deployment(False) as h:
        h.write_disk("a.txt", "hello world")
        result = await h.call("edit", {"file_path": "a.txt", "old_string": "world", "new_string": "there"})
        assert result.is_error is False
        assert h.read_disk("a.txt") == "hello there"
