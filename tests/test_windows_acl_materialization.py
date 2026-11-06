"""Real Win32 inheritance and restricted-token checks on owned ACL fixtures."""
import ctypes as c
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from dsh.sandbox.windows_acl import WinApi, SidAttributes, capability_sid
from dsh.sandbox.windows_acl_checks import WorkspaceAclError


pytestmark = pytest.mark.skipif(os.name != "nt", reason="actual Windows ACL materialization")
RUNNER = Path(__file__).resolve().parents[1] / "dsh/sandbox/windows_runner.py"


@pytest.fixture
def owned_acl(tmp_path):
    api = WinApi()
    guard = api.workspace_guard()
    adv = api.advapi
    for name, args in {
        "ConvertStringSecurityDescriptorToSecurityDescriptorW": [c.c_wchar_p, c.c_uint32, c.c_void_p, c.c_void_p],
        "SetFileSecurityW": [c.c_wchar_p, c.c_uint32, c.c_void_p],
        "ConvertSidToStringSidW": [c.c_void_p, c.c_void_p],
    }.items():
        fn = getattr(adv, name)
        fn.argtypes, fn.restype = args, c.c_int
    token = c.c_void_p()
    api.check(api.OpenProcessToken(api.GetCurrentProcess(), 8, c.byref(token)), "fixture token")
    try:
        user = api.token_info(token, 1)
        text = c.c_void_p()
        api.check(adv.ConvertSidToStringSidW(SidAttributes.from_buffer(user).sid,
                  c.byref(text)), "fixture SID")
        try:
            account = c.wstring_at(text)
        finally:
            api.LocalFree(text)
    finally:
        api.CloseHandle(token)

    def install(path, sddl, owner=False):
        descriptor = c.c_void_p()
        api.check(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            ("O:USER" + sddl).replace("USER", account), 1, c.byref(descriptor), None), "fixture parse")
        try:
            api.check(adv.SetFileSecurityW(str(path), 0x80000005 if owner else 0x80000004,
                      descriptor), "fixture set")
        finally:
            api.LocalFree(descriptor)

    def snapshot(path):
        return guard.named_snapshot(str(path))

    folder = tmp_path / "owned"
    folder.mkdir()
    install(folder, "D:P(A;OICI;FA;;;USER)", owner=True)
    try:
        yield api, folder, account, install, snapshot
    finally:
        # Restore only this fixture; never follow links or alter an external ACL.
        install(folder, "D:P(A;OICI;FA;;;USER)")
        for directory, dirs, files in os.walk(str(folder)):
            for path in [Path(directory)] + [Path(directory) / item for item in files]:
                assert not path.lstat().st_file_attributes & 0x400
                install(path, "D:P(A;OICI;FA;;;USER)")


def run(workspace, temp, code, extra=()):
    return subprocess.run([sys.executable, str(RUNNER), "--workspace", str(workspace),
                           "--temp", str(temp), "--mode", "workspace-write"] + list(extra) +
                          ["--", sys.executable, "-c", code], cwd=str(workspace),
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          encoding="utf-8", timeout=25)


@pytest.mark.parametrize("sddl,reason", [
    ("D:P(A;;FA;;;USER)", "inheritance-gap"),
    ("D:PNO_ACCESS_CONTROL", "null-dacl"),
    ("D:P", "empty-dacl"),
    ("D:P(A;OICINP;FA;;;USER)", "inheritance-gap"),
    ("D:P(D;OICI;FR;;;USER)(A;OICI;FA;;;USER)", "normal-access-missing"),
])
def test_dangerous_grant_refused_without_disk_changes(owned_acl, sddl, reason):
    api, folder, _account, install, snapshot = owned_acl
    install(folder, sddl)
    before = snapshot(folder)
    with pytest.raises(WorkspaceAclError) as caught:
        api.grant(str(folder), capability_sid(str(folder)))
    assert caught.value.reason == reason
    assert caught.value.modified is False
    assert caught.value.before == before
    assert snapshot(folder) == before
    install(folder, "D:P(A;OICI;FA;;;USER)")
    assert not list(folder.iterdir())


@pytest.mark.parametrize("sddl", [
    "D:P(A;OICI;0x1301bf;;;USER)",
    "D:P(A;OICI;FA;;;USER)",
    "D:P(A;;FA;;;USER)(A;OICIIO;FA;;;CO)",
    "D:P(A;;FA;;;USER)(A;OICI;0x1301bf;;;AU)",
])
def test_native_prediction_matches_real_nested_creation(owned_acl, sddl):
    api, folder, _account, install, snapshot = owned_acl
    install(folder, sddl)
    workspace, temp = folder / "workspace", folder / "temp"
    workspace.mkdir()
    temp.mkdir()
    install(workspace, sddl)
    first = api.grant(str(workspace), capability_sid(str(workspace)))
    assert api.grant(str(workspace), capability_sid(str(workspace))) == first
    assert snapshot(workspace).descriptor == first.descriptor
    code = ("from pathlib import Path; p=Path('one/two'); p.mkdir(parents=True); "
            "f=p/'result.md'; f.write_text('# converted',encoding='utf-8'); "
            "assert f.read_text(encoding='utf-8')=='# converted'; "
            "f.write_text('# edited',encoding='utf-8'); "
            "assert f.read_text(encoding='utf-8')=='# edited'; f.unlink(); "
            "p.rmdir(); p.parent.rmdir(); print('CLOSED_REOPENED_DELETED')")
    result = run(workspace, temp, code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CLOSED_REOPENED_DELETED"


def test_existing_capability_does_not_bypass_inheritance_check(owned_acl):
    api, folder, _account, install, snapshot = owned_acl
    sid = capability_sid(str(folder))
    install(folder, "D:P(A;;FA;;;USER)(A;OICI;0x110156;;;" + sid + ")")
    before = snapshot(folder)
    with pytest.raises(WorkspaceAclError, match="inheritance-gap"):
        api.grant(str(folder), sid)
    assert snapshot(folder) == before


def test_runner_refuses_payload_before_bad_root_materialization(owned_acl):
    _api, folder, _account, install, snapshot = owned_acl
    workspace, temp = folder / "workspace", folder / "temp"
    workspace.mkdir()
    temp.mkdir()
    install(workspace, "D:P(A;;FA;;;USER)")
    before = snapshot(workspace)
    result = run(workspace, temp, "print('PAYLOAD')")
    assert result.returncode == 127
    assert "windows-acl-run:" in result.stderr and "inheritance-gap" in result.stderr
    assert "PAYLOAD" not in result.stdout
    assert snapshot(workspace) == before
    assert not list(temp.iterdir())


@pytest.mark.parametrize("damage", ["missing", "inheritance", "temp"])
def test_preprovided_runner_rechecks_acl_before_payload(owned_acl, damage):
    api, folder, _account, install, snapshot = owned_acl
    workspace, private = folder / "workspace", folder / "private"
    workspace.mkdir()
    private.mkdir()
    sid, temp_sid = capability_sid(str(workspace)), capability_sid(str(private), True)
    api.grant(str(workspace), sid)
    api.grant(str(private), temp_sid)
    if damage == "missing":
        api.grant(str(workspace), sid, revoke=True)
    elif damage == "inheritance":
        install(workspace, "D:P(A;;FA;;;USER)(A;OICI;0x110156;;;" + sid + ")")
    else:
        install(private, "D:P(A;;FA;;;USER)(A;OICI;0x110156;;;" + temp_sid + ")")
    before = snapshot(workspace), snapshot(private)
    result = run(workspace, private, "print('PAYLOAD')",
                 ["--write-sid", sid, "--temp-write-sid", temp_sid])
    assert result.returncode == 127 and "PAYLOAD" not in result.stdout
    assert ("capability-missing" if damage == "missing" else "inheritance-gap") in result.stderr
    assert (snapshot(workspace), snapshot(private)) == before


def test_provider_rechecks_and_recovers_without_restart(owned_acl):
    from dsh.cordis.context import Context
    from dsh.sandbox.local import LocalSandboxProvider
    from dsh.sandbox.vocabulary import SandboxUnavailableError

    api, folder, _account, install, _snapshot = owned_acl
    provider = LocalSandboxProvider(Context())
    provider.api = api
    policy = {"mode": "workspace-write", "workspaceRoot": str(folder), "sessionId": "session"}
    payload = [sys.executable, "-c", "print('PAYLOAD')"]
    sid = capability_sid(str(folder))
    try:
        first = provider.confine(payload, policy)
        api.grant(str(folder), sid, revoke=True)
        assert provider.confine(payload, policy) == first
        api.validate_grant(str(folder), sid)
        install(folder, "D:P(A;;FA;;;USER)(A;OICI;0x110156;;;" + sid + ")")
        with pytest.raises(SandboxUnavailableError, match="inheritance-gap"):
            provider.confine(payload, policy)
        install(folder, "D:P(A;OICI;0x1301bf;;;USER)")
        assert provider.confine(payload, policy) == first
        result = subprocess.run(first["argv"], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", timeout=25)
        assert result.returncode == 0 and "PAYLOAD" in result.stdout, result.stderr
    finally:
        provider.dispose()


@pytest.mark.parametrize("failure", ["query", "apply", "verify", "race", "unsupported"])
def test_native_failures_report_stage_and_do_not_blindly_rollback(owned_acl, monkeypatch, failure):
    api, folder, _account, _install, snapshot = owned_acl
    guard = api.workspace_guard()
    before = snapshot(folder)
    sid = capability_sid(str(folder))
    real_apply = guard.SetSecurityInfo
    applications = []

    def apply(*args):
        applications.append(True)
        return 5 if failure == "apply" else real_apply(*args)

    monkeypatch.setattr(guard, "SetSecurityInfo", apply)
    if failure == "query":
        monkeypatch.setattr(api, "GetNamedSecurityInfoW", lambda *_: 5)
    elif failure == "verify":
        original = guard.snapshot

        def read(handle):
            if applications:
                raise OSError(5, "injected post-write query failure")
            return original(handle)

        monkeypatch.setattr(guard, "snapshot", read)
    elif failure == "race":
        original = guard.snapshot

        def read(handle):
            value = original(handle)
            return type(value)(value.identity, value.descriptor + b"drift", value.control, value.state)

        monkeypatch.setattr(guard, "snapshot", read)
    elif failure == "unsupported":
        def unsupported(_acl):
            raise ValueError("injected unsupported ACE")
        monkeypatch.setattr(guard, "supported_acl", unsupported)
    with pytest.raises(WorkspaceAclError) as caught:
        api.grant(str(folder), sid)
    error = caught.value
    expected = {"query": ("inspect", "query-failed"), "apply": ("apply", "apply-failed"),
                "verify": ("verify", "verify-failed"), "race": ("apply", "acl-changed"),
                "unsupported": ("assess", "assessment-unsupported")}[failure]
    assert (error.stage, error.reason) == expected
    assert error.modified is (failure == "verify")
    assert len(applications) == (1 if failure in ("apply", "verify") else 0)
    # Undo only mocks; inspect the real on-disk outcome, not the injected query result.
    monkeypatch.undo()
    after = snapshot(folder)
    assert (after != before) is (failure == "verify")


def test_independent_hosts_coordinate_grants(owned_acl):
    api, folder, _account, _install, snapshot = owned_acl
    sid = capability_sid(str(folder))

    def grant(_index):
        return WinApi().grant(str(folder), sid)

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(grant, range(2)))
    assert receipts[0] == receipts[1]
    assert snapshot(folder).descriptor == receipts[0].descriptor
    api.validate_grant(str(folder), sid)


def test_provider_refuses_replaced_temp_and_preserves_replacement(owned_acl, monkeypatch):
    from dsh.cordis.context import Context
    from dsh.sandbox.local import LocalSandboxProvider

    api, folder, _account, _install, _snapshot = owned_acl
    workspace = folder / "workspace"
    workspace.mkdir()
    import tempfile
    original_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: original_mkdtemp(dir=str(folder), **kwargs))
    provider = LocalSandboxProvider(Context())
    provider.api = api
    private, _sid = provider.materialize("session", str(workspace))
    path = Path(private)
    path.rename(folder / "held-original")
    path.mkdir()
    marker = path / "unowned.txt"
    marker.write_text("preserve", encoding="utf-8")
    try:
        with pytest.raises(OSError, match="identity changed"):
            provider.materialize("session", str(workspace))
    finally:
        provider.dispose()
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_acl_oracle_rejects_unreviewed_observations():
    from scripts.windows_acl_oracle import classify
    source = dict(mode="this-folder-only", grant="applied", changed=True,
                  newWrite=True, newRead=False, oldRead=True, reason=None)
    port = dict(mode="this-folder-only", grant="refused", changed=False,
                newWrite=None, newRead=None, oldRead=True, reason="inheritance-gap")
    assert classify(source, port) == "reviewed-upstream-bug/UPSTREAM-WINDOWS-ACL-001"
    assert classify(dict(source, oldRead=False), port) == "different"
    assert classify(source, dict(port, changed=True)) == "different"
    assert classify(source, dict(port, reason="query-failed")) == "different"


@pytest.mark.asyncio
async def test_pwsh_python_api_markdown_and_host_atomic_edit(owned_acl):
    import json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread
    from dsh.cordis.context import Context
    from dsh.fs.fs_local import FsService
    from dsh.sandbox.local import LocalSandboxProvider
    from dsh.sandbox.sandbox_policy import SandboxPolicyService
    from dsh.shell.pwsh_executor import SandboxPwshExecutor
    from dsh.subprocess.local import LocalSubprocessRuntime

    _api, folder, _account, _install, _snapshot = owned_acl
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({"markdown": "# converted\n"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = folder / "convert.py"
    client.write_text("""import json,sys,urllib.request
from pathlib import Path
request=urllib.request.Request(sys.argv[1],data=b'{}',headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request, timeout=5) as response:
    markdown=json.load(response)['markdown']
output=Path('converted/nested/result.md')
output.parent.mkdir(parents=True)
output.write_text(markdown,encoding='utf-8')
assert output.read_text(encoding='utf-8')==markdown
print('API_MARKDOWN_REOPENED')
""", encoding="utf-8")
    ctx, fibers = Context(), []
    try:
        for plugin, config in [(LocalSubprocessRuntime, {}), (LocalSandboxProvider, {}),
                               (SandboxPolicyService, {"mode": "workspace-write", "workspaceRoot": str(folder)}),
                               (SandboxPwshExecutor, {"cwd": str(folder)})]:
            fiber = ctx.plugin(plugin, config)
            await fiber.await_settled()
            fibers.append(fiber)
        command = "& '{}' '{}' 'http://127.0.0.1:{}/convert'".format(
            sys.executable.replace("'", "''"), str(client).replace("'", "''"), server.server_port)
        shell = ctx.get("shell")
        result = await shell.run(shell.resolve({"command": command, "timeoutMs": 15000}))
        assert result["exitCode"] == 0, result
        assert "API_MARKDOWN_REOPENED" in result["stdout"]["text"]
        assert requests == [b"{}"]
        output = folder / "converted/nested/result.md"
        fs = FsService(cwd=str(folder))
        await fs.writeText(await fs.resolve(str(output)), "# edited\n")
        assert output.read_text(encoding="utf-8") == "# edited\n"
        output.unlink()
        output.parent.rmdir()
        output.parent.parent.rmdir()
    finally:
        for fiber in reversed(fibers):
            await fiber.dispose()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
