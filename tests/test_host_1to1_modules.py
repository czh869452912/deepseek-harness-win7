"""
Unit tests for 1:1 host modules (injections, plugin_inventory, session_export, native_path_opener, directory_picker split).
"""

import io
import zipfile
import pytest

from dsh.cordis.context import Context
from dsh.host.apiproxy.native_path_opener import open_native_path
from dsh.host.apiproxy.session_export import export_session_ndjson, export_session_zip
from dsh.host.directory_picker.auto import DirectoryPickerAutoPlugin
from dsh.host.directory_picker.base import DirectoryPickerService
from dsh.host.directory_picker.browse import BrowseDirectoryPickerPlugin, BrowseDirectoryPickerService
from dsh.host.directory_picker.native import NativeDirectoryPickerPlugin, NativeDirectoryPickerService
from dsh.host.plugin_inventory import PluginInventoryGateway
from dsh.host.webserver.injections import render_index_injections


def test_render_index_injections():
    html = "<html><head><title>Test</title></head><body><div id='app'></div></body></html>"
    rows = [
        {"kind": "global", "name": "__DSH_CONFIG__", "value": {"env": "test"}},
        {"kind": "script", "placement": "body", "text": "console.log('ready');"},
        {"kind": "script-src", "placement": "head", "src": "/plugins/my-plugin/client.js"},
        {"kind": "style", "text": "body { margin: 0; }"},
        {"kind": "html", "placement": "body", "html": "<!-- injected html -->"},
    ]
    res = render_index_injections(html, rows)
    assert 'globalThis["__DSH_CONFIG__"] = {"env": "test"}' in res
    assert '<style>body { margin: 0; }</style>' in res
    assert '<script src="/plugins/my-plugin/client.js"></script>' in res
    assert '<script>console.log(\'ready\');</script>' in res
    assert '<!-- injected html -->' in res


def test_session_export_zip_and_ndjson():
    events = [
        {"type": "session/create", "sessionId": "s-1"},
        {"type": "user/message", "content": "hello"},
    ]
    ndjson_data = export_session_ndjson("s-1", events)
    assert b"session/create" in ndjson_data
    assert b"hello" in ndjson_data

    zip_bytes = export_session_zip("s-1", events)
    assert len(zip_bytes) > 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        assert "session-s-1/events.ndjson" in namelist
        assert "session-s-1/manifest.json" in namelist


def test_plugin_inventory_gateway():
    ctx = Context()
    gateway = PluginInventoryGateway(ctx)
    res = gateway.list()
    assert "entries" in res
    assert isinstance(res["entries"], list)


def test_directory_picker_submodules():
    ctx = Context()
    base_svc = BrowseDirectoryPickerService(ctx)
    cap = base_svc.capability()
    assert cap["kind"] == "browse"
    assert "list" in cap

    native_svc = NativeDirectoryPickerService(ctx)
    cap_native = native_svc.capability()
    assert cap_native["kind"] == "native"
    assert "pick" in cap_native


def test_native_path_opener():
    # Test open_native_path with non-existent file
    assert open_native_path("C:\\non_existent_path_xyz123") is False
