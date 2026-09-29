import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.storage.domain_error import DomainError
from dsh.storage.domain_spec import define_domain, domain_table, DomainGlobalSpec
from dsh.storage.error import StorageError
from dsh.storage.storage import Storage, StorageService
from dsh.storage.storage_sqlite import SqliteStorageBackend
from dsh.workspace.workspace import (
    WorkspaceOrderInvalidError,
    WorkspaceRegistry,
    WorkspaceService,
    WorkspaceUnknownSessionError,
)


def test_storage_domain_json_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = Context()
        storage = StorageService(ctx, root_dir=tmpdir)
        dom = storage.domain("test_settings")
        dom.set("theme", "dark")
        dom.set("fontSize", 14)

        assert dom.get("theme") == "dark"
        assert dom.get("fontSize") == 14
        assert set(dom.list_keys()) == {"theme", "fontSize"}
        assert dom.entries() == {"theme": "dark", "fontSize": 14}

        # Reopen from disk to test persistence
        ctx2 = Context()
        storage2 = StorageService(ctx2, root_dir=tmpdir)
        dom2 = storage2.domain("test_settings")
        assert dom2.get("theme") == "dark"
        assert dom2.get("fontSize") == 14

        assert "test_settings" in storage2.list_domains()

        dom2.delete("fontSize")
        assert dom2.get("fontSize") is None

        dom2.clear()
        assert len(dom2.list_keys()) == 0


async def workspace_context(tmp_path, headers=None):
    from dsh.storage.hub import Storage
    ctx = Context()
    Storage(ctx, root_dir=str(tmp_path / 'storage'))
    class Persistence:
        async def list(self):
            return headers or []
    ctx.set_service('sessionPersistence', Persistence())
    reg = WorkspaceRegistry(ctx)
    await reg.init()
    ctx.set_service('workspaceRegistry', reg)
    return ctx, reg


@pytest.mark.asyncio
async def test_workspace_registry_operations(tmp_path):
    path = tmp_path / 'project'
    path.mkdir()
    headers = [dict(id='session-123', cwd=str(path), createdAt=1000)]
    ctx, reg = await workspace_context(tmp_path, headers)
    try:
        ws = await reg.create(str(path), title='My Workspace')
        await ws.setTitle('My Workspace')
        assert (await reg.resolveByPath(str(path))).id == ws.id
        await ws.attachSession('session-123')
        assert ws.sessionIds == ['session-123']
        await ws.detachSession('session-123')
        assert ws.sessionIds == []
        await ws.attachSession('session-123')
        await reg.archiveSession('session-123')
        identity = ws.id
    finally:
        await ctx.fiber.dispose()
    ctx, reg = await workspace_context(tmp_path, headers)
    try:
        ws = reg.get(identity)
        assert ws.title == 'My Workspace'
        assert ws.sessionIds == ['session-123']
        assert reg.archivedSessionIds == ['session-123']
        assert await reg.delete(identity)
        assert reg.list() == []
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_domain_spec_and_sqlite_backend_1to1():
    # Test spec validation rules
    spec = define_domain(
        name="testdom",
        version=1,
        tables={"items": domain_table(lambda x: str(x))},
        global_spec=DomainGlobalSpec(schema=lambda x: str(x) if x is not None else (_ for _ in ()).throw(ValueError("null not allowed")), initial="default"),
    )
    assert spec.name == "testdom"

    with pytest.raises(ValueError, match="domain name 'Invalid-Name' must match"):
        define_domain(name="Invalid-Name", version=1, tables={})

    # Test SQLite backend
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        sqlite_backend = SqliteStorageBackend({"path": db_path})

        from dsh.storage.domain_spec import descriptor_of
        desc = descriptor_of(spec)
        unit = await sqlite_backend.kv.open(desc)

        await unit.put_record("items", "k1", "v1")
        await unit.set_global("global_val")

        snapshot = await unit.load_all()
        assert snapshot["tables"]["items"]["k1"] == "v1"
        assert snapshot["global"] == "global_val"

        await unit.delete_record("items", "k1")
        snapshot2 = await unit.load_all()
        assert "k1" not in snapshot2["tables"]["items"]

        await unit.close()
        await sqlite_backend.close()


@pytest.mark.asyncio
async def test_workspace_insert_before_and_archive_1to1(tmp_path):
    ctx, reg = await workspace_context(tmp_path)

    with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
        ws1 = await reg.create(tmpdir1, title="WS 1")
        ws2 = await reg.create(tmpdir2, title="WS 2")

        # Initial list order
        items = reg.list()
        assert len(items) == 2

        # Reorder ws2 before ws1
        new_order = await reg.insert_before(ws2.id, ws1.id)
        assert new_order == [ws2.id, ws1.id]

        # Invalid reorder ID raises WorkspaceOrderInvalidError
        with pytest.raises(WorkspaceOrderInvalidError):
            await reg.insert_before("unknown-id")

        # Unknown session archive raises WorkspaceUnknownSessionError
        with pytest.raises(WorkspaceUnknownSessionError):
            await reg.archive_session("nonexistent-session")

    await ctx.fiber.dispose()
