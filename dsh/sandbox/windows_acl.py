"""Win7 restricted tokens and capability ACLs; no unrestricted fallback.

The boundary is deliberately partial, like the pinned Windows provider:
Everyone grants and hard links are not a complete filesystem security boundary.
ctypes structures use native pointer alignment on both 32- and 64-bit Python.
"""
import ctypes as c
from ctypes import wintypes as w
from contextlib import contextmanager
import hashlib
import os
import subprocess
import tempfile


P = c.c_void_p
D = w.DWORD
GRANT_MASK = (0x120116 | 0x10000 | 0x40) & ~0x20000


class SidAttributes(c.Structure):
    _fields_ = [("sid", P), ("attributes", D)]


class Groups(c.Structure):
    _fields_ = [("count", D), ("groups", SidAttributes * 1)]


class Trustee(c.Structure):
    _fields_ = [("multiple", P), ("operation", D), ("form", D),
                ("type", D), ("name", P)]


class Access(c.Structure):
    _fields_ = [("permissions", D), ("mode", D), ("inherit", D),
                ("trustee", Trustee)]


class Overlapped(c.Structure):
    _fields_ = [("internal", c.c_size_t), ("high", c.c_size_t),
                ("offset", D), ("offsetHigh", D), ("event", P)]


class Startup(c.Structure):
    _fields_ = [("cb", D), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
                ("title", w.LPWSTR), ("x", D), ("y", D), ("cx", D),
                ("cy", D), ("charsX", D), ("charsY", D), ("fill", D),
                ("flags", D), ("show", w.WORD), ("reservedSize", w.WORD),
                ("reservedPtr", P), ("stdin", P), ("stdout", P), ("stderr", P)]


class Process(c.Structure):
    _fields_ = [("process", P), ("thread", P), ("pid", D), ("tid", D)]


class BasicLimit(c.Structure):
    _fields_ = [("processTime", c.c_longlong), ("jobTime", c.c_longlong),
                ("flags", D), ("minWorkingSet", c.c_size_t),
                ("maxWorkingSet", c.c_size_t), ("activeProcessLimit", D),
                ("affinity", c.c_size_t), ("priority", D), ("scheduling", D)]


class JobLimit(c.Structure):
    _fields_ = [("basic", BasicLimit), ("io", c.c_ulonglong * 6),
                ("processMemory", c.c_size_t), ("jobMemory", c.c_size_t),
                ("peakProcessMemory", c.c_size_t), ("peakJobMemory", c.c_size_t)]


def capability_sid(path, temporary=False):
    digest = hashlib.sha256((("temp\0" if temporary else "") + path).encode("utf-8")).digest()
    parts = [int.from_bytes(digest[n:n + 4], "little") % (2 ** 30 - 1) + 1 for n in (0, 4)]
    return "S-1-4-{}-{}{}".format(parts[0], parts[1], "-1" if temporary else "")


def assert_temp_outside(workspace, temp):
    workspace, temp = [os.path.normcase(os.path.realpath(p)) for p in (workspace, temp)]
    try:
        inside = os.path.commonpath([workspace, temp]) == workspace
    except ValueError:
        inside = False
    if inside:
        raise ValueError("private temp root must be outside the workspace")


class WinApi:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows ACL confinement requires Windows")
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.advapi = c.WinDLL("advapi32", use_last_error=True)
        definitions = {
            "GetCurrentProcess": (P, []), "CloseHandle": (w.BOOL, [P]),
            "LocalFree": (P, [P]), "GetStdHandle": (P, [D]),
            "SetHandleInformation": (w.BOOL, [P, D, D]),
            "CreateJobObjectW": (P, [P, w.LPCWSTR]),
            "SetInformationJobObject": (w.BOOL, [P, c.c_int, P, D]),
            "AssignProcessToJobObject": (w.BOOL, [P, P]),
            "ResumeThread": (D, [P]), "TerminateProcess": (w.BOOL, [P, D]),
            "WaitForSingleObject": (D, [P, D]), "GetExitCodeProcess": (w.BOOL, [P, P]),
            "CreateFileW": (P, [w.LPCWSTR, D, D, P, D, D, P]),
            "LockFileEx": (w.BOOL, [P, D, D, D, D, P]),
            "UnlockFileEx": (w.BOOL, [P, D, D, D, P]),
        }
        security = {
            "OpenProcessToken": (w.BOOL, [P, D, P]),
            "GetTokenInformation": (w.BOOL, [P, c.c_int, P, D, P]),
            "SetTokenInformation": (w.BOOL, [P, c.c_int, P, D]),
            "ConvertStringSidToSidW": (w.BOOL, [w.LPCWSTR, P]),
            "GetLengthSid": (D, [P]), "EqualSid": (w.BOOL, [P, P]),
            "CreateRestrictedToken": (w.BOOL, [P, D, D, P, D, P, D, P, P]),
            "SetEntriesInAclW": (D, [D, P, P, P]),
            "GetNamedSecurityInfoW": (D, [w.LPCWSTR, c.c_int, D, P, P, P, P, P]),
            "SetNamedSecurityInfoW": (D, [w.LPWSTR, c.c_int, D, P, P, P, P]),
            "CreateProcessAsUserW": (w.BOOL, [P, w.LPCWSTR, w.LPWSTR, P, P,
                                                w.BOOL, D, P, w.LPCWSTR, P, P]),
        }
        for dll, entries in ((self.kernel, definitions), (self.advapi, security)):
            for name, (result, args) in entries.items():
                fn = getattr(dll, name)
                fn.restype, fn.argtypes = result, args
                setattr(self, name, fn)

    def check(self, value, name):
        if not value:
            self.error(name, c.get_last_error())
        return value

    def status(self, value, name):
        if value:
            self.error(name, value)

    @staticmethod
    def error(name, code):
        raise OSError(code, "{}: Win32 {}: {}".format(name, code, c.FormatError(code)))

    @contextmanager
    def sid(self, text):
        value = P()
        self.check(self.ConvertStringSidToSidW(text, c.byref(value)), "ConvertStringSidToSidW")
        try:
            yield value
        finally:
            self.LocalFree(value)

    @contextmanager
    def path_lock(self, path):
        root = os.path.join(tempfile.gettempdir(), "dsh-acl-locks")
        os.makedirs(root, exist_ok=True)
        digest = hashlib.sha256(path.lower().encode("utf-8")).hexdigest()[:16]
        handle = self.CreateFileW(os.path.join(root, digest + ".lock"), 0xc0000000, 3, None, 4, 0, None)
        if handle == P(-1).value:
            self.error("CreateFileW ACL lock", c.get_last_error())
        overlapped = Overlapped()
        try:
            self.check(self.LockFileEx(handle, 2, 0, 1, 0, c.byref(overlapped)), "LockFileEx")
            try:
                yield
            finally:
                self.check(self.UnlockFileEx(handle, 0, 1, 0, c.byref(overlapped)), "UnlockFileEx")
        finally:
            self.CloseHandle(handle)

    def exact_grant(self, acl, sid):
        if not acl.value:
            return False
        size = c.c_ushort.from_address(acl.value + 2).value
        count = c.c_ushort.from_address(acl.value + 4).value
        offset = 8
        for _ in range(count):
            if offset + 8 > size:
                return False
            address = acl.value + offset
            ace_size = c.c_ushort.from_address(address + 2).value
            if ace_size < 16 or offset + ace_size > size:
                return False
            if (c.c_ubyte.from_address(address).value == 0
                    and c.c_ubyte.from_address(address + 1).value == 3
                    and D.from_address(address + 4).value == GRANT_MASK
                    and self.EqualSid(address + 8, sid)):
                return True
            offset += ace_size
        return False

    @staticmethod
    def entry(sid, revoke=False, permissions=GRANT_MASK):
        return Access(0 if revoke else permissions, 4 if revoke else 1, 3,
                      Trustee(None, 0, 0, 0, sid))

    def grant(self, path, sid_text, revoke=False):
        with self.path_lock(path), self.sid(sid_text) as sid:
            old, descriptor, new = P(), P(), P()
            self.status(self.GetNamedSecurityInfoW(path, 1, 4, None, None,
                        c.byref(old), None, c.byref(descriptor)), "GetNamedSecurityInfoW")
            try:
                if (not revoke and self.exact_grant(old, sid)) or (revoke and not old.value):
                    return
                entry = self.entry(sid, revoke)
                self.status(self.SetEntriesInAclW(1, c.byref(entry), old, c.byref(new)), "SetEntriesInAclW")
                self.status(self.SetNamedSecurityInfoW(path, 1, 4, None, None, new, None), "SetNamedSecurityInfoW")
            finally:
                if new.value:
                    self.LocalFree(new)
                if descriptor.value:
                    self.LocalFree(descriptor)

    def token_info(self, token, kind):
        size = D()
        self.GetTokenInformation(token, kind, None, 0, c.byref(size))
        self.check(size.value, "GetTokenInformation size")
        buffer = c.create_string_buffer(size.value)
        self.check(self.GetTokenInformation(token, kind, buffer, size, c.byref(size)), "GetTokenInformation")
        return buffer

    @contextmanager
    def restricted_token(self, write_sids):
        from contextlib import ExitStack
        current, restricted = P(), P()
        self.check(self.OpenProcessToken(self.GetCurrentProcess(), 0x8b, c.byref(current)), "OpenProcessToken")
        try:
            groups = self.token_info(current, 2)
            count = D.from_buffer(groups).value
            logon = None
            for index in range(count):
                group = SidAttributes.from_buffer(groups, Groups.groups.offset + index * c.sizeof(SidAttributes))
                if group.attributes & 0xc0000000 == 0xc0000000:
                    logon = group.sid
                    break
            if logon is None:
                raise OSError("restricted token requires a logon SID")
            with ExitStack() as stack:
                world = stack.enter_context(self.sid("S-1-1-0"))
                writes = [stack.enter_context(self.sid(text)) for text in write_sids]
                sids = [logon, world] + writes
                entries = (SidAttributes * len(sids))(*[SidAttributes(sid, 0) for sid in sids])
                self.check(self.CreateRestrictedToken(current, 0xd, 0, None, 0, None,
                           len(sids), entries, c.byref(restricted)), "CreateRestrictedToken")
                # New pipes need an ACE recognized by the second token access check.
                original = self.token_info(restricted, 6)
                old = P.from_buffer(original)
                self.check(old.value, "TokenDefaultDacl")
                new = P()
                entry = self.entry(writes[0] if writes else world, permissions=0x1f01ff)
                self.status(self.SetEntriesInAclW(1, c.byref(entry), old, c.byref(new)), "SetEntriesInAclW token")
                try:
                    self.check(self.SetTokenInformation(restricted, 6, c.byref(new), c.sizeof(new)), "SetTokenInformation")
                finally:
                    self.LocalFree(new)
                yield restricted
        finally:
            if restricted.value:
                self.CloseHandle(restricted)
            self.CloseHandle(current)

    def run(self, token, argv, cwd):
        """Suspend -> assign kill-on-close Job -> resume, inheriting only stdio.

        This runs in a dedicated runner process, which owns no unrelated
        inheritable handles. Failure to assign a Job kills the suspended child.
        """
        job = self.check(self.CreateJobObjectW(None, None), "CreateJobObjectW")
        process = Process()
        try:
            limit = JobLimit()
            limit.basic.flags = 0x2000
            self.check(self.SetInformationJobObject(job, 9, c.byref(limit), c.sizeof(limit)), "SetInformationJobObject")
            startup = Startup()
            startup.cb, startup.flags = c.sizeof(startup), 0x100
            startup.show = 0
            for field, selector in (("stdin", -10), ("stdout", -11), ("stderr", -12)):
                handle = self.GetStdHandle(selector)
                self.check(handle and handle != P(-1).value, "GetStdHandle")
                self.check(self.SetHandleInformation(handle, 1, 1), "SetHandleInformation")
                setattr(startup, field, handle)
            command = c.create_unicode_buffer(subprocess.list2cmdline(argv))
            self.check(self.CreateProcessAsUserW(token, None, command, None, None, True,
                       4 | 0x08000000, None, cwd, c.byref(startup), c.byref(process)), "CreateProcessAsUserW")
            self.check(self.AssignProcessToJobObject(job, process.process), "AssignProcessToJobObject")
            if self.ResumeThread(process.thread) == 0xffffffff:
                self.error("ResumeThread", c.get_last_error())
            if self.WaitForSingleObject(process.process, 0xffffffff) != 0:
                self.error("WaitForSingleObject", c.get_last_error())
            code = D()
            self.check(self.GetExitCodeProcess(process.process, c.byref(code)), "GetExitCodeProcess")
            return code.value
        finally:
            if process.process:
                self.TerminateProcess(process.process, 1)
            self.CloseHandle(job)
            if process.thread:
                self.CloseHandle(process.thread)
            if process.process:
                self.CloseHandle(process.process)
