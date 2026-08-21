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

        # Reopen from disk to test persistence
        storage2 = StorageService(ctx, root_dir=tmpdir)
        dom2 = storage2.domain("test_settings")
        assert dom2.get("theme") == "dark"
        assert dom2.get("fontSize") == 14

        dom2.delete("fontSize")
        assert dom2.get("fontSize") is None


def test_workspace_registry_operations():
    ctx = Context()
    ws_svc = WorkspaceService(ctx)

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = ws_svc.create(tmpdir, title="My Workspace")
        assert ws.workspace_id.startswith("ws-")
        assert ws.title == "My Workspace"

        ws_svc.bind_session(ws.workspace_id, "session-123")
        assert "session-123" in ws.session_ids

        all_ws = ws_svc.list_workspaces()
        assert len(all_ws) == 1
        assert all_ws[0].workspace_id == ws.workspace_id
