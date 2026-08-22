import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.storage.storage import StorageService
from dsh.workspace.workspace import WorkspaceService


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
        storage2 = StorageService(ctx, root_dir=tmpdir)
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
