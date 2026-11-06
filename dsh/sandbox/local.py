"""Local confinement service with provider-owned Windows temp capabilities."""
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile

from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.sandbox.vocabulary import SandboxUnavailableError
from dsh.sandbox.windows_acl import (WinApi, assert_temp_outside, capability_sid,
                                     temp_directory_identity, verify_temp_identity)


def bwrap_profile(policy):
    args = ["--ro-bind", "/", "/", "--dev", "/dev", "--unshare-pid", "--proc", "/proc", "--die-with-parent"]
    if policy["mode"] == "workspace-write":
        args += ["--tmpfs", "/tmp", "--bind", policy["workspaceRoot"], policy["workspaceRoot"]]
    return args


class LocalSandboxProvider(Service):
    Config = Schema.object({
        "runnerCommand": Schema.array(Schema.string()).default([]),
        "runnerFailureSignatures": Schema.array(Schema.string()).default([]),
        "probeTimeoutMs": Schema.number().default(5000),
    })

    def __init__(self, ctx, config=None):
        config = config or {}
        self.runner = list(config.get("runnerCommand", []))
        self.signatures = list(config.get("runnerFailureSignatures", []))
        self.timeout = config.get("probeTimeoutMs", 5000)
        if bool(self.runner) != bool(self.signatures):
            raise ValueError("sandbox-local: runnerCommand and runnerFailureSignatures must be supplied together")
        if any(not isinstance(s, str) or not s.strip() or "\r" in s or "\n" in s for s in self.signatures):
            raise ValueError("sandbox-local: runnerFailureSignatures must be non-empty single-line strings")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("sandbox-local: probeTimeoutMs must be a positive finite number")
        self.temps = {}
        self.api = None
        self._acl_recovery = None
        self.closed = False
        self.selected = None
        super().__init__(ctx, "sandbox")
        ctx.effect(lambda: self.dispose)

    def apply(self, ctx=None, config=None):
        pass

    def acl_recovery(self):
        if self.closed or sys.platform != "win32" or self.runner:
            raise ValueError("host Windows ACL recovery is unavailable for this provider")
        if self.api is None:
            self.api = WinApi()
        if self._acl_recovery is None:
            from dsh.sandbox.windows_acl_recovery import WindowsAclRecovery
            self._acl_recovery = WindowsAclRecovery(self.api)
        return self._acl_recovery

    def confine(self, argv, policy):
        mode = policy["mode"]
        if self.closed:
            raise SandboxUnavailableError(mode, "provider disposed")
        if mode not in ("workspace-write", "read-only"):
            raise ValueError("confine requires a confined mode")
        if not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("confine requires a non-empty argv")
        if self.runner:
            return self.result(self.runner + bwrap_profile(policy) + ["--"] + list(argv), "full",
                               ["read-only file system", "permission denied"], [{"fatalSignatures": self.signatures}])
        if sys.platform == "win32":
            invocation = [sys.executable, os.path.join(os.path.dirname(__file__), "windows_runner.py")]
            temp = tempfile.gettempdir()
            extra = []
            if mode == "workspace-write" and policy.get("sessionId") is not None:
                try:
                    temp, sid = self.materialize(policy["sessionId"], policy["workspaceRoot"])
                except Exception as error:
                    raise SandboxUnavailableError(mode, str(error) +
                        " Use workspace_acl inspect for host-side diagnosis without starting pwsh; "
                        "workspace_acl plan/repair offers a separate approved directory repair.") from error
                extra = ["--write-sid", capability_sid(policy["workspaceRoot"]), "--temp-write-sid", sid]
            invocation += ["--workspace", policy["workspaceRoot"], "--temp", temp, "--mode", mode] + extra
            return self.result(invocation + ["--"] + list(argv), "partial",
                               ["access is denied", "access to the path", "permission denied",
                                "unauthorizedaccessexception", "permissiondenied"],
                               [{"allowedExitCodes": [127], "fatalSignatures": ["windows-acl-run: "]}])
        if sys.platform == "darwin":
            profile = '(version 1) (allow default) (deny file-write*) (allow file-write* (literal "/dev/null"))'
            if mode == "workspace-write":
                profile += ' (allow file-write* (subpath "/private/tmp") (subpath {}) (subpath {}))'.format(json.dumps(tempfile.gettempdir()), json.dumps(policy["workspaceRoot"]))
            return self.result(["sandbox-exec", "-p", profile, "--"] + list(argv), "full",
                               ["operation not permitted"], [{"fatalSignatures": ["sandbox-exec: "]}])
        if sys.platform.startswith("linux"):
            # The portable Python distribution contains no Node Landlock addon.
            # Only claim the real, functionally verified bwrap backend here.
            if self.selected is None:
                try:
                    probe = subprocess.run(["bwrap"] + bwrap_profile({"mode": "read-only"}) + ["--", "true"],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, timeout=self.timeout / 1000)
                    self.selected = probe.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    self.selected = False
            if self.selected:
                return self.result(["bwrap"] + bwrap_profile(policy) + ["--"] + list(argv), "full",
                                   ["read-only file system"], [{"fatalSignatures": ["bwrap: "]}])
        raise SandboxUnavailableError(mode)

    @staticmethod
    def result(argv, enforcement, denials, failures):
        return {"argv": argv, "enforcement": enforcement,
                "denialSignatures": denials, "runnerFailureRules": failures}

    def materialize(self, session_id, workspace):
        assert_temp_outside(workspace, tempfile.gettempdir())
        if self.api is None:
            self.api = WinApi()
        # A previous grant is not evidence of the directory's current ACL.
        self.api.grant(workspace, capability_sid(workspace))
        key = (str(session_id), workspace)
        if key not in self.temps:
            directory = tempfile.mkdtemp(prefix="dsh-")
            sid = capability_sid(directory, True)
            identity = temp_directory_identity(directory)
            try:
                self.api.grant(directory, sid)
            except BaseException:
                try:
                    verify_temp_identity(directory, identity)
                    self.api.grant(directory, sid, revoke=True)
                except Exception as error:
                    logging.getLogger("sandbox-local").warning("private temp revoke failed: %s", error)
                try:
                    verify_temp_identity(directory, identity)
                    shutil.rmtree(directory)
                except Exception as error:
                    logging.getLogger("sandbox-local").warning("private temp cleanup failed: %s", error)
                raise
            self.temps[key] = (directory, sid, identity)
        else:
            directory, sid, identity = self.temps[key]
            verify_temp_identity(directory, identity)
            self.api.validate_grant(directory, sid)
        return self.temps[key][:2]

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        if self._acl_recovery is not None:
            self._acl_recovery.clear()
        failures = []
        for directory, sid, identity in self.temps.values():
            try:
                verify_temp_identity(directory, identity)
                self.api.grant(directory, sid, revoke=True)
            except Exception as error:
                failures.append(error)
            try:
                verify_temp_identity(directory, identity)
                shutil.rmtree(directory)
            except Exception as error:
                failures.append(error)
        self.temps.clear()
        for error in failures:
            logging.getLogger("sandbox-local").warning("private temp cleanup failed: %s", error)
