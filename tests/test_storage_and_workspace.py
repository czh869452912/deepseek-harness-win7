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


def test_workspace_registry_operations():
    ctx = Context()
    events = []

    def on_event(name):
        return lambda data: events.append((name, data))

    ctx.on("workspace:created", on_event("created"))
    ctx.on("workspace:session-bound", on_event("bound"))
    ctx.on("workspace:session-unbound", on_event("unbound"))
    ctx.on("workspace:deleted", on_event("deleted"))

    ws_svc = WorkspaceService(ctx)

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = ws_svc.create(tmpdir, title="My Workspace")
        assert ws.workspace_id.startswith("ws-")
        assert ws.title == "My Workspace"

        by_path = ws_svc.get_by_path(tmpdir)
        assert by_path is not None
        assert by_path.workspace_id == ws.workspace_id

        ws_svc.bind_session(ws.workspace_id, "session-123")
        assert "session-123" in ws.session_ids

        all_ws = ws_svc.list_workspaces()
        assert len(all_ws) == 1
        assert all_ws[0].workspace_id == ws.workspace_id

        ws_svc.unbind_session(ws.workspace_id, "session-123")
        assert "session-123" not in ws.session_ids

        ws_svc.touch(ws.workspace_id)
        ws_svc.delete(ws.workspace_id)
        assert ws_svc.get(ws.workspace_id) is None
        assert len(ws_svc.list_workspaces()) == 0

        event_names = [e[0] for e in events]
        assert "created" in event_names
        assert "bound" in event_names
        assert "unbound" in event_names
        assert "deleted" in event_names


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
async def test_workspace_insert_before_and_archive_1to1():
    ctx = Context()
    reg = WorkspaceRegistry(ctx)
    await reg.init()

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
