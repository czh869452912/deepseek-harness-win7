"""Preflight capability grants without creating objects in a user's workspace."""
import ctypes as c
from ctypes import wintypes as w
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib


P = c.c_void_p
D = w.DWORD


class GenericMapping(c.Structure):
    _fields_ = [("read", D), ("write", D), ("execute", D), ("all", D)]


class SecurityDescriptor(c.Structure):
    _fields_ = [("revision", c.c_ubyte), ("reserved", c.c_ubyte),
                ("control", w.WORD), ("owner", P), ("group", P),
                ("sacl", P), ("dacl", P)]


class FileInformation(c.Structure):
    _fields_ = [("attributes", D), ("created", w.FILETIME), ("accessed", w.FILETIME),
                ("written", w.FILETIME), ("volume", D), ("sizeHigh", D),
                ("sizeLow", D), ("links", D), ("indexHigh", D), ("indexLow", D)]


@dataclass(frozen=True)
class AclSnapshot:
    identity: tuple
    descriptor: bytes
    control: int
    state: str

    @property
    def fingerprint(self):
        return hashlib.sha256(self.descriptor).hexdigest()


class WorkspaceAclError(OSError):
    def __init__(self, path, sid, stage, reason, detail, modified=False, winerror=None):
        self.stage, self.reason = stage, reason
        self.capability_sid, self.modified = sid, modified
        self.before = self.after = None
        message = ("workspace ACL stage={} reason={} capability={} modified={}: {}. "
                   "Check this directory's normal user/group permissions and inheritance; "
                   "do not delete capability SIDs or reset the directory tree. "
                   "Use workspace_acl inspect for host-side diagnosis, then plan/repair "
                   "for a separately approved directory repair.").format(
                       stage, reason, sid, modified, detail)
        super().__init__(winerror or 5, message, path)
        self.winerror = winerror


class WorkspaceAclGuard:
    def __init__(self, api):
        self.api = api
        definitions = {
            "GetFileInformationByHandle": (w.BOOL, [P, P]),
        }
        security = {
            "GetSecurityInfo": (D, [P, c.c_int, D, P, P, P, P, P]),
            "SetSecurityInfo": (D, [P, c.c_int, D, P, P, P, P]),
            "GetSecurityDescriptorLength": (D, [P]),
            "IsValidSecurityDescriptor": (w.BOOL, [P]),
            "IsValidAcl": (w.BOOL, [P]),
            "GetSecurityDescriptorDacl": (w.BOOL, [P, P, P, P]),
            "GetSecurityDescriptorControl": (w.BOOL, [P, P, P]),
            "GetSecurityDescriptorOwner": (w.BOOL, [P, P, P]),
            "GetSecurityDescriptorGroup": (w.BOOL, [P, P, P]),
            "CreatePrivateObjectSecurityEx": (w.BOOL, [P, P, P, P, w.BOOL, D, P, P]),
            "DestroyPrivateObjectSecurity": (w.BOOL, [P]),
            "DuplicateToken": (w.BOOL, [P, c.c_int, P]),
            "AccessCheck": (w.BOOL, [P, P, D, P, P, P, P, P]),
        }
        for dll, entries in ((api.kernel, definitions), (api.advapi, security)):
            for name, (result, args) in entries.items():
                fn = getattr(dll, name)
                fn.restype, fn.argtypes = result, args
                setattr(self, name, fn)
        self.mapping = GenericMapping(0x120089, 0x120116, 0x1200a0, 0x1f01ff)

    @contextmanager
    def directory(self, path, write=False):
        # An explicit access mask permits inheritance propagation; MAXIMUM_ALLOWED does not.
        handle = self.api.CreateFileW(path, 0x20000 | (0x40000 if write else 0),
                                      3, None, 3, 0x42000000, None)
        if handle == P(-1).value:
            self.api.error("CreateFileW ACL directory", c.get_last_error())
        try:
            yield handle
        finally:
            self.api.CloseHandle(handle)

    def identity(self, handle):
        info = FileInformation()
        self.api.check(self.GetFileInformationByHandle(handle, c.byref(info)),
                       "GetFileInformationByHandle ACL")
        if not info.attributes & 0x10:
            raise ValueError("ACL target is not a directory")
        return info.volume, info.indexHigh, info.indexLow

    def parts(self, descriptor):
        self.api.check(self.IsValidSecurityDescriptor(descriptor), "IsValidSecurityDescriptor")
        present, defaulted, acl = w.BOOL(), w.BOOL(), P()
        self.api.check(self.GetSecurityDescriptorDacl(descriptor, c.byref(present),
                       c.byref(acl), c.byref(defaulted)), "GetSecurityDescriptorDacl")
        control, revision = w.WORD(), D()
        self.api.check(self.GetSecurityDescriptorControl(descriptor, c.byref(control),
                       c.byref(revision)), "GetSecurityDescriptorControl")
        if not present.value:
            state = "absent-dacl"
        elif not acl.value:
            state = "null-dacl"
        else:
            self.api.check(self.IsValidAcl(acl), "IsValidAcl")
            state = "empty-dacl" if c.c_ushort.from_address(acl.value + 4).value == 0 else "acl"
        return acl, control.value, state

    def supported_acl(self, acl):
        size = c.c_ushort.from_address(acl.value + 2).value
        count = c.c_ushort.from_address(acl.value + 4).value
        offset = 8
        for _ in range(count):
            kind = c.c_ubyte.from_address(acl.value + offset).value
            if kind not in (0, 1):
                raise ValueError("unsupported ACE type {} (only ordinary Allow/Deny are assessed)".format(kind))
            offset += c.c_ushort.from_address(acl.value + offset + 2).value
        if offset > size:
            raise ValueError("ACE bounds exceed the ACL")

    def principals(self, descriptor):
        owner, group, defaulted = P(), P(), w.BOOL()
        self.api.check(self.GetSecurityDescriptorOwner(descriptor, c.byref(owner),
                       c.byref(defaulted)), "GetSecurityDescriptorOwner")
        self.api.check(self.GetSecurityDescriptorGroup(descriptor, c.byref(group),
                       c.byref(defaulted)), "GetSecurityDescriptorGroup")
        return tuple(c.string_at(sid, self.api.GetLengthSid(sid)) for sid in (owner, group))

    def snapshot(self, handle):
        descriptor = P()
        self.api.status(self.GetSecurityInfo(handle, 1, 7, None, None, None, None,
                        c.byref(descriptor)), "GetSecurityInfo ACL")
        try:
            _acl, control, state = self.parts(descriptor)
            length = self.GetSecurityDescriptorLength(descriptor)
            self.api.check(length, "GetSecurityDescriptorLength")
            return AclSnapshot(self.identity(handle), c.string_at(descriptor, length), control, state)
        finally:
            if descriptor.value:
                self.api.LocalFree(descriptor)

    def named_snapshot(self, path):
        # This API can read an owner's DACL even when CreateFileW itself is denied.
        descriptor = P()
        self.api.status(self.api.GetNamedSecurityInfoW(path, 1, 7, None, None, None, None,
                        c.byref(descriptor)), "GetNamedSecurityInfoW ACL")
        try:
            _acl, control, state = self.parts(descriptor)
            length = self.GetSecurityDescriptorLength(descriptor)
            self.api.check(length, "GetSecurityDescriptorLength")
            return AclSnapshot((), c.string_at(descriptor, length), control, state)
        finally:
            if descriptor.value:
                self.api.LocalFree(descriptor)

    def candidate(self, original, acl):
        owner, group, defaulted = P(), P(), w.BOOL()
        self.api.check(self.GetSecurityDescriptorOwner(original, c.byref(owner),
                       c.byref(defaulted)), "GetSecurityDescriptorOwner")
        self.api.check(self.GetSecurityDescriptorGroup(original, c.byref(group),
                       c.byref(defaulted)), "GetSecurityDescriptorGroup")
        _old, control, _state = self.parts(original)
        return SecurityDescriptor(1, 0, (control & ~0x8000) | 4, owner, group, None, acl)

    @contextmanager
    def inherited(self, parent, token, directory):
        descriptor = P()
        self.api.check(self.CreatePrivateObjectSecurityEx(parent, None, c.byref(descriptor),
                       None, directory, 1, token, c.byref(self.mapping)), "CreatePrivateObjectSecurityEx")
        try:
            yield descriptor
        finally:
            self.DestroyPrivateObjectSecurity(c.byref(descriptor))

    @contextmanager
    def impersonation(self, token):
        duplicate = P()
        self.api.check(self.DuplicateToken(token, 2, c.byref(duplicate)), "DuplicateToken ACL")
        try:
            yield duplicate
        finally:
            self.api.CloseHandle(duplicate)

    def allows(self, descriptor, token, mask):
        size = D(1024)
        privileges = c.create_string_buffer(size.value)
        granted, allowed = D(), w.BOOL()
        result = self.AccessCheck(descriptor, token, mask, c.byref(self.mapping),
                                  privileges, c.byref(size), c.byref(granted), c.byref(allowed))
        if not result and c.get_last_error() == 122:
            privileges = c.create_string_buffer(size.value)
            result = self.AccessCheck(descriptor, token, mask, c.byref(self.mapping),
                                      privileges, c.byref(size), c.byref(granted), c.byref(allowed))
        self.api.check(result, "AccessCheck ACL")
        return bool(allowed.value)

    def assess(self, descriptor, sid_text):
        current = P()
        self.api.check(self.api.OpenProcessToken(self.api.GetCurrentProcess(), 0xa,
                       c.byref(current)), "OpenProcessToken ACL")
        try:
            with self.api.restricted_token([sid_text]) as restricted:
                for name, primary in (("host", current), ("restricted", restricted)):
                    with self.impersonation(primary) as token:
                        if not self.allows(descriptor, token, 0x1201bf):
                            return "normal-access-missing", name + " cannot read/write/traverse the root"
                        # Both directory generations matter: NO_PROPAGATE may allow only level one.
                        with self.inherited(descriptor, primary, True) as child:
                            with self.inherited(child, primary, True) as grandchild:
                                for parent, label in ((descriptor, "root"), (child, "child"),
                                                      (grandchild, "grandchild")):
                                    if not self.allows(parent, token, 0x1201bf):
                                        return "inheritance-gap", name + " lacks directory access at " + label
                                    with self.inherited(parent, primary, False) as file_sd:
                                        if not self.allows(file_sd, token, 0x12019f):
                                            return "inheritance-gap", name + " cannot reopen a new file at " + label
                                        if not (self.allows(file_sd, token, 0x10000)
                                                or self.allows(parent, token, 0x40)):
                                            return "inheritance-gap", name + " cannot delete a new file at " + label
                                    if label != "root" and not (self.allows(parent, token, 0x10000)
                                            or self.allows(descriptor if label == "child" else child, token, 0x40)):
                                        return "inheritance-gap", name + " cannot delete a new directory at " + label
        finally:
            self.api.CloseHandle(current)
        return None

    def ensure(self, path, sid_text, validate_only=False):
        stage, modified, before, after = "inspect", False, None, None
        try:
            with self.api.path_lock(path), self.api.sid(sid_text) as sid:
                before = self.named_snapshot(path)
                if before.state != "acl":
                    raise WorkspaceAclError(path, sid_text, stage, before.state,
                                            "a real, nonempty DACL is required")
                original = c.create_string_buffer(before.descriptor)
                old, _control, _state = self.parts(original)
                existing = self.api.exact_grant(old, sid)
                if validate_only and not existing:
                    raise WorkspaceAclError(path, sid_text, "validate", "capability-missing",
                                            "the supplied capability is not present on disk")
                stage = "assess"
                self.supported_acl(old)
                new = P()
                try:
                    if existing:
                        candidate = original
                    else:
                        entry = self.api.entry(sid)
                        self.api.status(self.api.SetEntriesInAclW(1, c.byref(entry), old,
                                        c.byref(new)), "SetEntriesInAclW ACL candidate")
                        absolute = self.candidate(original, new)
                        candidate = c.byref(absolute)
                    refusal = self.assess(candidate, sid_text)
                    if refusal:
                        raise WorkspaceAclError(path, sid_text, stage, *refusal)
                    stage = "apply" if not existing else "verify"
                    with self.directory(path) as handle:
                        bound = self.snapshot(handle)
                        if bound.descriptor != before.descriptor:
                            raise WorkspaceAclError(path, sid_text, "apply", "acl-changed",
                                                    "the target changed after assessment")
                        before = bound
                        if not existing:
                            stage = "apply"
                            with self.directory(path, write=True) as writable:
                                if self.snapshot(writable) != before:
                                    raise WorkspaceAclError(path, sid_text, stage, "acl-changed",
                                                            "the target changed before the grant")
                                self.api.status(self.SetSecurityInfo(writable, 1, 4, None, None,
                                                new, None), "SetSecurityInfo ACL")
                                modified = True
                        stage = "verify"
                        after = self.snapshot(handle)
                        # Reopen by path to detect alias/ancestor retargeting as well as descriptor drift.
                        with self.directory(path) as live:
                            if self.snapshot(live) != after or after.identity != before.identity:
                                raise WorkspaceAclError(path, sid_text, stage, "acl-changed",
                                                        "the target changed during verification", modified)
                        actual = c.create_string_buffer(after.descriptor)
                        actual_acl, _flags, state = self.parts(actual)
                        if (state != "acl" or not self.api.exact_grant(actual_acl, sid)
                                or (after.control ^ before.control) & 0x1000
                                or self.principals(actual) != self.principals(original)):
                            raise WorkspaceAclError(path, sid_text, stage, "verify-failed",
                                                    "the grant or protection state did not survive", modified)
                        if after != before:
                            self.supported_acl(actual_acl)
                            refusal = self.assess(actual, sid_text)
                            if refusal:
                                raise WorkspaceAclError(path, sid_text, stage, *refusal, modified=modified)
                        return after
                finally:
                    if new.value:
                        self.api.LocalFree(new)
        except Exception as error:
            if not isinstance(error, WorkspaceAclError):
                reason = {"inspect": "query-failed", "assess": "assessment-unsupported",
                          "apply": "apply-failed", "verify": "verify-failed"}[stage]
                error = WorkspaceAclError(path, sid_text, stage, reason, str(error),
                                          modified, getattr(error, "winerror", None) or getattr(error, "errno", None))
            error.modified = modified
            error.before, error.after = before, after
            raise error
