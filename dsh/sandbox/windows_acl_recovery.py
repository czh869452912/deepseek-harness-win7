"""Host-side diagnosis and approved, snapshot-bound directory ACL recovery."""
import base64
import ctypes as c
import json
import os
import secrets
import stat
import tempfile
import time
from contextlib import contextmanager

from dsh.sandbox.windows_acl import P, SidAttributes, capability_sid
from dsh.sandbox.windows_acl_metadata import AclMetadata


MODIFY = 0x1301bf
PROPAGATION = ("Windows may propagate this inheritable grant to existing inheriting descendants, "
               "including other workspaces below this directory. Protected descendants are not reset. "
               "The backup covers the selected directory, not a recursive rollback.")


class WindowsAclRecovery:
    def __init__(self, api):
        self.api = api
        self.guard = api.workspace_guard()
        self.metadata = AclMetadata(api)
        self.plans = {}
        for name, args in {
            "ConvertSidToStringSidW": [P, P],
            "ConvertSecurityDescriptorToStringSecurityDescriptorW": [P, c.c_uint32, c.c_uint32, P, P],
            "InitializeAcl": [P, c.c_uint32, c.c_uint32],
            "AddAce": [P, c.c_uint32, c.c_uint32, P, c.c_uint32],
            "AddAccessAllowedAceEx": [P, c.c_uint32, c.c_uint32, c.c_uint32, P],
        }.items():
            fn = getattr(api.advapi, name)
            fn.argtypes, fn.restype = args, c.c_int
            setattr(self, name, fn)

    def clear(self):
        self.plans.clear()

    def sid_text(self, sid):
        text = P()
        self.api.check(self.ConvertSidToStringSidW(sid, c.byref(text)), "ConvertSidToStringSidW")
        try:
            return c.wstring_at(text)
        finally:
            self.api.LocalFree(text)

    def account(self):
        token = P()
        self.api.check(self.api.OpenProcessToken(self.api.GetCurrentProcess(), 8, c.byref(token)),
                       "OpenProcessToken ACL recovery")
        try:
            user = self.api.token_info(token, 1)
            return self.sid_text(SidAttributes.from_buffer(user).sid)
        finally:
            self.api.CloseHandle(token)

    def sddl(self, snapshot):
        buffer = c.create_string_buffer(snapshot.descriptor)
        text = P()
        self.api.check(self.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            buffer, 1, 7, c.byref(text), None), "ConvertSecurityDescriptorToStringSecurityDescriptorW")
        try:
            return c.wstring_at(text)
        finally:
            self.api.LocalFree(text)

    @staticmethod
    def path(policy, value=None):
        root = os.path.normcase(os.path.abspath(policy["workspaceRoot"]))
        path = os.path.normcase(os.path.abspath(os.path.join(root, value) if value else root))
        try:
            common = os.path.commonpath([root, path])
        except ValueError:
            raise ValueError("ACL target must be the workspace, a descendant, or an explicit ancestor")
        if common not in (root, path):
            raise ValueError("ACL target must be the workspace, a descendant, or an explicit ancestor")
        return root, path

    def identity_chain(self, path):
        chain = []
        cursor = path
        while True:
            info = os.lstat(cursor)
            if not stat.S_ISDIR(info.st_mode) or info.st_file_attributes & 0x400:
                raise ValueError("ACL recovery requires identifiable directories without reparse components")
            with self.metadata.directory(cursor) as handle:
                chain.append((cursor, self.metadata.identity(handle)))
            parent = os.path.dirname(cursor)
            if cursor == parent:
                return tuple(chain)
            cursor = parent

    @contextmanager
    def add_allow(self, original, sid_text, mask):
        old, _control, state = self.guard.parts(original)
        if state != "acl":
            raise ValueError("automatic additive repair requires a nonempty DACL; "
                             "NULL, absent and empty DACLs require administrator review")
        self.guard.supported_acl(old)
        with self.api.sid(sid_text) as sid:
            size = c.c_ushort.from_address(old.value + 2).value + 8 + self.api.GetLengthSid(sid)
            buffer = c.create_string_buffer(size)
            new = c.cast(buffer, P)
            revision = c.c_ubyte.from_address(old.value).value
            self.api.check(self.InitializeAcl(new, size, revision), "InitializeAcl recovery")
            offset, added = 8, False
            # Preserve every existing ACE byte and its relative order. SetEntriesInAclW
            # GRANT_ACCESS can remove an existing Deny for the same SID.
            for _ in range(c.c_ushort.from_address(old.value + 4).value):
                address = old.value + offset
                ace_size = c.c_ushort.from_address(address + 2).value
                if not added and c.c_ubyte.from_address(address + 1).value & 16:
                    self.api.check(self.AddAccessAllowedAceEx(new, revision, 3, mask, sid),
                                   "AddAccessAllowedAceEx recovery")
                    added = True
                self.api.check(self.AddAce(new, revision, 0xffffffff, address, ace_size), "AddAce recovery")
                offset += ace_size
            if not added:
                self.api.check(self.AddAccessAllowedAceEx(new, revision, 3, mask, sid),
                               "AddAccessAllowedAceEx recovery")
            descriptor = self.guard.candidate(original, new)
            yield new, descriptor

    @contextmanager
    def candidate(self, snapshot, account):
        original = c.create_string_buffer(snapshot.descriptor)
        with self.add_allow(original, account, MODIFY) as (new, descriptor):
            yield original, new, descriptor

    def assess(self, descriptor, path, workspace=None):
        """Predict normal execution without persisting a capability grant."""
        from dsh.sandbox.windows_acl import GRANT_MASK
        # The provider's SID hashes its original path spelling, not a case-folded key.
        sid_path = workspace if workspace and os.path.normcase(os.path.abspath(workspace)) == path else path
        sid_text = capability_sid(sid_path)
        with self.add_allow(descriptor, sid_text, GRANT_MASK) as (_new, candidate):
            return self.guard.assess(c.byref(candidate), sid_text)

    def has_modify(self, descriptor, account):
        acl, _control, state = self.guard.parts(descriptor)
        if state != "acl":
            return False
        offset = 8
        with self.api.sid(account) as sid:
            for _ in range(c.c_ushort.from_address(acl.value + 4).value):
                address = acl.value + offset
                flags = c.c_ubyte.from_address(address + 1).value
                if (c.c_ubyte.from_address(address).value == 0 and flags & 15 == 3
                        and c.c_uint32.from_address(address + 4).value & MODIFY == MODIFY
                        and self.api.EqualSid(address + 8, sid)):
                    return True
                offset += c.c_ushort.from_address(address + 2).value
        return False

    def inspect(self, policy, value=None):
        root, path = self.path(policy, value)
        report = {"workspace": root, "accountSid": self.account(), "directories": [],
                  "guidance": "Use workspace_acl plan, then repair with its planId for an approved "
                              "directory repair. This tool runs in the host even when pwsh cannot start."}
        # A bounded ancestor report does not enumerate the workspace's contents.
        cursor = path
        for _ in range(16):
            item = {"path": cursor}
            try:
                snapshot = self.guard.named_snapshot(cursor)
                item.update(state=snapshot.state, protected=bool(snapshot.control & 0x1000),
                            fingerprint=snapshot.fingerprint, sddl=self.sddl(snapshot))
                self.identity_chain(cursor)
                if snapshot.state == "acl":
                    descriptor = c.create_string_buffer(snapshot.descriptor)
                    self.guard.supported_acl(self.guard.parts(descriptor)[0])
                    refusal = self.assess(descriptor, cursor, policy["workspaceRoot"])
                    item.update(ready=refusal is None, reason=refusal[0] if refusal else None)
                else:
                    item.update(ready=False, reason=snapshot.state)
            except (OSError, ValueError) as error:
                item.update(ready=False, error=str(error))
            report["directories"].append(item)
            parent = os.path.dirname(cursor)
            if parent == cursor:
                break
            cursor = parent
        return report

    def plan(self, policy, value=None):
        root, path = self.path(policy, value)
        if path == os.path.dirname(path):
            raise ValueError("refusing to repair a drive or share root; select a dedicated project directory")
        temp = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        if os.path.splitdrive(path)[0] == os.path.splitdrive(temp)[0] and os.path.commonpath([path, temp]) == path:
            raise ValueError("repair scope contains host TEMP; select a dedicated project directory")
        chain = self.identity_chain(path)
        account = self.account()
        with self.api.path_lock(path), self.metadata.directory(path, write=True) as handle:
            before = self.metadata.snapshot(handle)
            with self.candidate(before, account) as (_original, _new, candidate):
                refusal = self.assess(c.byref(candidate), path, policy["workspaceRoot"])
                if refusal:
                    raise ValueError("additive repair cannot resolve {}: {}".format(*refusal))
            if self.identity_chain(path) != chain:
                raise ValueError("ACL target identity changed while planning")
        now = time.monotonic()
        self.plans = {key: item for key, item in self.plans.items() if item["expires"] > now}
        if len(self.plans) >= 16:
            self.plans.pop(next(iter(self.plans)))
        plan_id = secrets.token_hex(16)
        public = dict(planId=plan_id, path=path, accountSid=account, beforeSddl=self.sddl(before),
                      grant="(OI)(CI) Modify for the current host account", propagation=PROPAGATION,
                      outsideWorkspace=path != root and os.path.commonpath([root, path]) == path,
                      expiresInSeconds=600)
        self.plans[plan_id] = dict(public=public, before=before, chain=chain, root=root,
                                  session=policy.get("sessionId"), expires=now + 600)
        return dict(public)

    def get_plan(self, policy, plan_id):
        item = self.plans.get(plan_id)
        root, _path = self.path(policy)
        if (not item or item["expires"] <= time.monotonic() or item["root"] != root
                or item["session"] != policy.get("sessionId") or item["public"]["accountSid"] != self.account()):
            raise ValueError("ACL repair plan missing, expired, or belongs to another session; create a new plan")
        return item

    def preview(self, policy, plan_id):
        return dict(self.get_plan(policy, plan_id)["public"])

    def repair(self, policy, plan_id):
        # The tool consumer must obtain allowed-once approval before calling this mutation.
        if policy["mode"] == "read-only":
            raise ValueError("ACL repair is unavailable in read-only mode; change the session mode explicitly")
        item = self.get_plan(policy, plan_id)
        del self.plans[plan_id]
        public, before = item["public"], item["before"]
        path, account = public["path"], public["accountSid"]
        with self.api.path_lock(path), self.metadata.directory(path, write=True) as handle:
            if self.identity_chain(path) != item["chain"] or self.metadata.snapshot(handle) != before:
                raise ValueError("ACL changed after planning; no repair applied; create a new plan")
            with self.candidate(before, account) as (original, acl, candidate):
                refusal = self.assess(c.byref(candidate), path, policy["workspaceRoot"])
                if refusal:
                    raise ValueError("repair no longer passes assessment: {}".format(refusal))
                backup_dir = tempfile.mkdtemp(prefix="dsh-acl-recovery-")
                backup = os.path.join(backup_dir, "directory-acl.json")
                backup_data = dict(public, identity=list(before.identity),
                                   descriptorBase64=base64.b64encode(before.descriptor).decode("ascii"))
                with open(backup, "x", encoding="utf-8") as stream:
                    json.dump(backup_data, stream, ensure_ascii=True, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                with open(backup, "r", encoding="utf-8") as stream:
                    if json.load(stream) != backup_data:
                        raise ValueError("ACL backup could not be verified; no permissions changed")
                if self.identity_chain(path) != item["chain"] or self.metadata.snapshot(handle) != before:
                    raise ValueError("ACL changed before repair; no repair applied; backup: " + backup)
                try:
                    self.api.status(self.guard.SetSecurityInfo(handle, 1, 4, None, None, acl, None),
                                    "SetSecurityInfo approved ACL recovery")
                    after = self.metadata.snapshot(handle)
                    actual = c.create_string_buffer(after.descriptor)
                    if (self.identity_chain(path) != item["chain"]
                            or self.guard.named_snapshot(path).descriptor != after.descriptor
                            or self.guard.principals(original) != self.guard.principals(actual)
                            or (after.control ^ before.control) & 0x1000
                            or not self.has_modify(actual, account)):
                        raise ValueError("directory identity, principals or protection changed during repair")
                    refusal = self.assess(actual, path, policy["workspaceRoot"])
                    if refusal:
                        raise ValueError("post-repair assessment failed: {}".format(refusal))
                except Exception as error:
                    raise OSError("ACL repair failed or needs review; permissions may have changed; "
                                  "no automatic rollback. Backup: {}. {}".format(backup, error)) from error
        # A repaired ancestor does not imply a protected workspace below it is repaired.
        workspace = self.inspect(policy)["directories"][0]
        return dict(path=path, repaired=True, backup=backup, afterSddl=self.sddl(after),
                    workspaceReady=workspace.get("ready", False), workspaceCheck=workspace,
                    propagation=PROPAGATION,
                    next="Retry the original pwsh call normally if workspaceReady; otherwise inspect "
                         "and plan the remaining directory. Existing protected descendants may need separate repair.")
