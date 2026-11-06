"""Actual pinned Windows grant versus the port's bounded ACL preflight fix."""
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def classify(left, right):
    for mode, reason, write in (("this-folder-only", "inheritance-gap", True),
                                ("protected-null", "null-dacl", False)):
        expected_source = dict(mode=mode, grant="applied", changed=True, newWrite=write,
                               newRead=False, oldRead=True, reason=None)
        expected_python = dict(mode=mode, grant="refused", changed=False, newWrite=None,
                               newRead=None, oldRead=True, reason=reason)
        if left == expected_source and right == expected_python:
            return "reviewed-upstream-bug/UPSTREAM-WINDOWS-ACL-001"
    return "different"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", default="node")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        raise ValueError("refusing to overwrite an existing observation: " + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status="runner-error", cases=[], platform=platform.platform(), python=sys.version)
    started = time.monotonic()
    fixture = None
    install = None
    try:
        if os.name != "nt":
            raise RuntimeError("requires real Windows; no simulated upstream observations")
        target = json.loads((ROOT / "migration/baseline.json").read_text(encoding="utf-8"))["target_upstream"]
        actual = subprocess.check_output(["git", "-C", str(ROOT / "reference"), "rev-parse", "HEAD"],
                                         encoding="utf-8").strip()
        dirty = subprocess.check_output(["git", "-C", str(ROOT / "reference"), "status", "--porcelain",
                                        "--untracked-files=no"], encoding="utf-8").strip()
        if target != actual or dirty:
            raise ValueError("reference must be clean at the pinned target")
        report["target_upstream"] = target
        inputs = ["scripts/windows_acl_oracle.py", "scripts/oracles/windows-acl-grant.mjs",
                  "dsh/sandbox/windows_acl.py", "dsh/sandbox/windows_acl_checks.py",
                  "reference/packages/sandbox/sandbox-windows-acl/src/grant.ts",
                  "reference/packages/sandbox/sandbox-windows-acl/src/acl.ts",
                  "reference/packages/sandbox/sandbox-windows-acl/src/workspace-sid.ts"]
        report["input_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs}
        from dsh.sandbox.windows_acl import WinApi, SidAttributes, capability_sid
        from dsh.sandbox.windows_acl_checks import WorkspaceAclError
        api = WinApi()
        guard = api.workspace_guard()
        adv = api.advapi
        for name, params in {
            "ConvertStringSecurityDescriptorToSecurityDescriptorW": [c.c_wchar_p, c.c_uint32, c.c_void_p, c.c_void_p],
            "SetFileSecurityW": [c.c_wchar_p, c.c_uint32, c.c_void_p],
            "ConvertSidToStringSidW": [c.c_void_p, c.c_void_p],
        }.items():
            fn = getattr(adv, name)
            fn.argtypes, fn.restype = params, c.c_int
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

        def install(path, sddl):
            descriptor = c.c_void_p()
            api.check(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl.replace("USER", account), 1, c.byref(descriptor), None), "parse fixture")
            try:
                api.check(adv.SetFileSecurityW(str(path), 0x80000004, descriptor), "set fixture")
            finally:
                api.LocalFree(descriptor)

        def attempt(operation):
            try:
                operation()
                return True, None
            except OSError as error:
                return False, dict(type=type(error).__name__, errno=error.errno,
                                   winerror=getattr(error, "winerror", None), message=str(error))

        fixture = Path(tempfile.mkdtemp(prefix="dsh-acl-paired-"))
        report["fixture"] = str(fixture)
        install(fixture, "D:P(A;OICI;FA;;;USER)")
        for mode in ("this-folder-only", "protected-null"):
            observations = []
            raw = []
            for provider in ("upstream", "python"):
                folder = fixture / (mode + "-" + provider)
                folder.mkdir()
                install(folder, "D:P(A;;FA;;;USER)" if mode == "this-folder-only" else "D:PNO_ACCESS_CONTROL")
                old = folder / "old.txt"
                old.write_text("old", encoding="utf-8")
                before = guard.named_snapshot(str(folder))
                row = dict(mode=mode, grant="applied", changed=None, newWrite=None,
                           newRead=None, oldRead=None, reason=None)
                details = dict(provider=provider, before=before.descriptor.hex())
                if provider == "upstream":
                    command = [args.node, "--import", (ROOT / "reference/node_modules/tsx/dist/esm/index.mjs").as_uri(),
                               str(ROOT / "scripts/oracles/windows-acl-grant.mjs"), str(folder)]
                    run = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", timeout=35)
                    details.update(command=command, exit=run.returncode, stdout=run.stdout, stderr=run.stderr)
                    if run.returncode:
                        raise RuntimeError("upstream grant failed: " + run.stderr)
                    result = json.loads(run.stdout)
                    if result.get("sid") != capability_sid(str(folder)) or result.get("granted") is not True:
                        raise ValueError("upstream capability differs from the port")
                else:
                    try:
                        api.grant(str(folder), capability_sid(str(folder)))
                    except WorkspaceAclError as error:
                        row.update(grant="refused", reason=error.reason)
                        details["refusal"] = dict(stage=error.stage, reason=error.reason,
                                                   modified=error.modified, message=str(error))
                after = guard.named_snapshot(str(folder))
                details["after"] = after.descriptor.hex()
                row["changed"] = before != after
                if row["grant"] == "applied":
                    new = folder / "new.md"
                    row["newWrite"], details["writeError"] = attempt(lambda: new.write_text("new", encoding="utf-8"))
                    row["newRead"], details["readError"] = attempt(lambda: new.read_text(encoding="utf-8"))
                row["oldRead"], details["oldReadError"] = attempt(lambda: old.read_text(encoding="utf-8"))
                observations.append(row)
                raw.append(details)
                install(folder, "D:P(A;OICI;FA;;;USER)")
            left, right = observations
            report["cases"].append(dict(mode=mode, status=classify(left, right), upstream=left, python=right, raw=raw))
        report["status"] = "passed" if all(row["status"] != "different" for row in report["cases"]) else "different"
    except Exception as error:
        report["error"] = str(error)
    finally:
        if fixture is not None and install is not None:
            try:
                assert fixture.parent == Path(tempfile.gettempdir()) and fixture.name.startswith("dsh-acl-paired-")
                install(fixture, "D:P(A;OICI;FA;;;USER)")
                for directory, dirs, files in os.walk(str(fixture)):
                    for path in [Path(directory)] + [Path(directory) / name for name in dirs + files]:
                        assert not path.lstat().st_file_attributes & 0x400
                        install(path, "D:P(A;OICI;FA;;;USER)")
                shutil.rmtree(str(fixture))
                report["cleanup"] = dict(ok=True, exists=fixture.exists())
            except Exception as error:
                report["cleanup"] = dict(ok=False, error=str(error))
                report["status"] = "runner-error"
        report["elapsed_seconds"] = time.monotonic() - started
        output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(report["status"], [(row["mode"], row["status"]) for row in report["cases"]])
    return {"passed": 0, "different": 1, "runner-error": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
