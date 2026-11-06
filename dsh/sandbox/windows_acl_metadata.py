"""Open ACL metadata without implicitly requiring FILE_READ_ATTRIBUTES.

CreateFileW can fail on a capability-only DACL even for its owner. Native
metadata handles still enforce READ_CONTROL/WRITE_DAC and enable no privileges.
"""
import ctypes as c
from ctypes import wintypes as w
from contextlib import contextmanager

from dsh.sandbox.windows_acl import P
from dsh.sandbox.windows_acl_checks import AclSnapshot


class UnicodeString(c.Structure):
    _fields_ = [("length", w.WORD), ("maximum", w.WORD), ("buffer", P)]


class ObjectAttributes(c.Structure):
    _fields_ = [("length", w.ULONG), ("root", P), ("name", P), ("attributes", w.ULONG),
                ("descriptor", P), ("quality", P)]


class IoStatus(c.Structure):
    _fields_ = [("status", P), ("information", c.c_size_t)]


class AclMetadata:
    def __init__(self, api):
        self.api, self.guard = api, api.workspace_guard()
        self.ntdll = c.WinDLL("ntdll", use_last_error=True)
        for name, result, args in (
                ("NtOpenFile", c.c_long, [P, w.DWORD, P, P, w.ULONG, w.ULONG]),
                ("NtQueryInformationFile", c.c_long, [P, P, P, w.ULONG, c.c_int]),
                ("NtQueryVolumeInformationFile", c.c_long, [P, P, P, w.ULONG, c.c_int]),
                ("RtlNtStatusToDosError", w.ULONG, [c.c_long])):
            fn = getattr(self.ntdll, name)
            fn.restype, fn.argtypes = result, args
            setattr(self, name, fn)

    def check(self, status, name):
        if status < 0:
            self.api.error(name, self.RtlNtStatusToDosError(status))

    @contextmanager
    def directory(self, path, write=False):
        if path.startswith("\\\\?\\"):
            native = "\\??\\" + path[4:]
        elif path.startswith("\\\\"):
            native = "\\??\\UNC\\" + path[2:]
        else:
            native = "\\??\\" + path
        name_buffer = c.create_unicode_buffer(native)
        length = len(native.encode("utf-16-le"))
        name = UnicodeString(length, length + 2, c.cast(name_buffer, P))
        attributes = ObjectAttributes(c.sizeof(ObjectAttributes), None, c.cast(c.pointer(name), P),
                                      0x40, None, None)
        handle, status = P(), IoStatus()
        self.check(self.NtOpenFile(c.byref(handle), 0x20000 | (0x40000 if write else 0),
                   c.byref(attributes), c.byref(status), 3, 0x200001), "NtOpenFile ACL metadata")
        try:
            yield handle
        finally:
            self.api.CloseHandle(handle)

    def identity(self, handle):
        status, index, volume = IoStatus(), c.c_ulonglong(), c.create_string_buffer(1024)
        self.check(self.NtQueryInformationFile(handle, c.byref(status), c.byref(index),
                   c.sizeof(index), 6), "FileInternalInformation ACL metadata")
        self.check(self.NtQueryVolumeInformationFile(handle, c.byref(status), volume,
                   c.sizeof(volume), 1), "FileFsVolumeInformation ACL metadata")
        if not index.value:
            raise ValueError("ACL target has no stable file identity")
        return c.c_uint32.from_buffer(volume, 8).value, index.value >> 32, index.value & 0xffffffff

    def snapshot(self, handle):
        descriptor = P()
        self.api.status(self.guard.GetSecurityInfo(handle, 1, 7, None, None, None, None,
                        c.byref(descriptor)), "GetSecurityInfo ACL metadata")
        try:
            _acl, control, state = self.guard.parts(descriptor)
            length = self.guard.GetSecurityDescriptorLength(descriptor)
            self.api.check(length, "GetSecurityDescriptorLength ACL metadata")
            return AclSnapshot(self.identity(handle), c.string_at(descriptor, length), control, state)
        finally:
            if descriptor.value:
                self.api.LocalFree(descriptor)
