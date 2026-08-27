import asyncio
import codecs
import errno
import inspect
import os
import pathlib
import shutil
import stat as stat_module
import sys
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union

from dsh.cordis.plugin import Plugin


PACKAGE_NAME = "@deepseek-ai/dsh-fs-local"
PACKAGE_VERSION = "0.1.1-rc.2"
DEFAULT_DIFF_BASIS_MAX_BYTES = 10 * 1024 * 1024
MAX_DIFF_BASIS_BYTES = sys.maxsize
BINARY_SAMPLE_BYTES = 8192
READ_CHUNK_BYTES = 64 * 1024


class FsError(Exception):
    def __init__(self, message: str, code: str, cause: Optional[BaseException] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.cause = cause


class FsTarget:
    def __init__(self, target_key: str, display_path: str):
        self.targetKey = target_key
        self.displayPath = display_path

    @property
    def target_key(self) -> str:
        return self.targetKey

    @property
    def display_path(self) -> str:
        return self.displayPath

    def __repr__(self) -> str:
        return "FsTarget(targetKey=%r, displayPath=%r)" % (self.targetKey, self.displayPath)


class FsInfo:
    def __init__(self, version: str, type_: str, size: Optional[int] = None):
        self.version = version
        self.type = type_
        self.size = size


class FsPathInfo(FsInfo):
    pass


class FsDirEntry:
    def __init__(self, name: str, type_: str, target: FsTarget, version: Optional[str] = None, size: Optional[int] = None):
        self.name = name
        self.type = type_
        self.target = target
        self.version = version
        self.size = size


class FsWriteOutcome:
    def __init__(self, operation: str, version: str, before: Optional[str], after: str):
        self.operation = operation
        self.version = version
        self.before = before
        self.after = after


class FsEditOutcome:
    def __init__(self, version: str, before: str, after: str):
        self.version = version
        self.before = before
        self.after = after


class FsIoInternals:
    """Optional native-boundary hooks used to make filesystem races testable."""

    def __init__(self):
        self.platform = None
        self.tempDirName = None
        self.tempName = None
        self.copyFileDacl = None
        self.replaceFile = None
        self.linkFile = None
        self.inspectPublicationTarget = None
        self.removeStagingDir = None
        self.inspectTemp = None
        self.inspectReadBytesAfterStat = None


class FsConfig:
    def __init__(self, cwd: str, diff_basis_max_bytes: int):
        self.cwd = cwd
        self.diffBasisMaxBytes = diff_basis_max_bytes


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _signal_aborted(signal: Optional[Any]) -> bool:
    if signal is None:
        return False
    checker = getattr(signal, "is_set", None)
    if callable(checker):
        return bool(checker())
    return bool(getattr(signal, "aborted", False))


def _throw_if_aborted(signal: Optional[Any], verb: str) -> None:
    if _signal_aborted(signal):
        raise FsError("%s aborted" % verb, "FS_ABORTED")


def _version_of(info: os.stat_result) -> str:
    return "%s:%s:%s:%s:%s" % (
        info.st_dev,
        info.st_ino,
        info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1000000000)),
        getattr(info, "st_ctime_ns", int(info.st_ctime * 1000000000)),
    )


def _path_type(info: os.stat_result) -> str:
    if stat_module.S_ISREG(info.st_mode):
        return "file"
    if stat_module.S_ISDIR(info.st_mode):
        return "directory"
    return "other"


def _normalize_line_endings(content: str) -> str:
    return content.replace("\r\n", "\n")


def _detect_line_endings(content: str) -> str:
    sample = content[:4096]
    crlf_count = sample.count("\r\n")
    lf_count = sample.count("\n") - crlf_count
    return "CRLF" if crlf_count > lf_count else "LF"


def _restore_line_endings(content: str, line_endings: str) -> str:
    return content if line_endings == "LF" else _normalize_line_endings(content).replace("\n", "\r\n")


def _decode_utf8(raw: bytes, verb: str, display_path: str) -> str:
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise FsError('cannot %s "%s": invalid UTF-8 text' % (verb, display_path), "FS_NOT_TEXT", error)


def _is_missing(error: OSError) -> bool:
    return error.errno in (errno.ENOENT, errno.ENOTDIR)


def _is_permission(error: OSError) -> bool:
    return error.errno in (errno.EACCES, errno.EPERM)


def _to_namespaced_path(path: str) -> str:
    """Return the Win32 extended-length spelling, including UNC paths."""
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + os.path.abspath(path)


def _from_namespaced_path(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _native_path(path: str) -> str:
    return _to_namespaced_path(path) if os.name == "nt" else path


def _real_path(path: str) -> str:
    return _from_namespaced_path(os.path.realpath(_native_path(path)))


def _path_exists(path: str, follow: bool = True) -> bool:
    try:
        os.stat(_native_path(path)) if follow else os.lstat(_native_path(path))
        return True
    except OSError as error:
        if _is_missing(error):
            return False
        return False


class FsService:
    """Windows 7 compatible local filesystem provider."""

    package_name = PACKAGE_NAME
    package_version = PACKAGE_VERSION

    def __init__(self, cwd: Optional[str] = None, diff_basis_max_bytes: int = DEFAULT_DIFF_BASIS_MAX_BYTES):
        if (isinstance(diff_basis_max_bytes, bool) or not isinstance(diff_basis_max_bytes, int)
                or diff_basis_max_bytes <= 0 or diff_basis_max_bytes > MAX_DIFF_BASIS_BYTES):
            raise ValueError("fs-local: diffBasisMaxBytes must be a positive safe integer no greater than %s" % MAX_DIFF_BASIS_BYTES)
        self.cwd = cwd if cwd is not None else os.getcwd()
        self.diff_basis_max_bytes = diff_basis_max_bytes
        self.config = FsConfig(self.cwd, diff_basis_max_bytes)
        self.internals = FsIoInternals()
        self._locks: Dict[str, asyncio.Lock] = {}
        self._lock_users: Dict[str, int] = {}

    @property
    def sandboxMode(self) -> Optional[str]:
        return None

    @property
    def sandbox_mode(self) -> Optional[str]:
        return None

    def _display_path(self, path: str, cwd: Optional[str] = None) -> str:
        base = self.cwd if cwd is None else cwd
        return os.path.abspath(path if os.path.isabs(path) else os.path.join(base, path))

    def _resolve_target(self, path: str, cwd: Optional[str] = None) -> FsTarget:
        if not isinstance(path, str) or not path.strip():
            raise FsError("file_path must be a non-empty string", "FS_NOT_FOUND")
        display = self._display_path(path, cwd)
        if _path_exists(display):
            return FsTarget(_real_path(display), display)
        missing: List[str] = [os.path.basename(display)]
        ancestor = os.path.dirname(display)
        while True:
            if _path_exists(ancestor, follow=False):
                try:
                    ancestor_info = os.stat(_native_path(ancestor))
                except OSError:
                    ancestor_info = None
                if ancestor_info is None or not stat_module.S_ISDIR(ancestor_info.st_mode):
                    raise FsError('cannot resolve "%s": a parent path segment is not a directory' % display, "FS_NOT_FOUND")
                return FsTarget(os.path.join(_real_path(ancestor), *missing), display)
            parent = os.path.dirname(ancestor)
            if parent == ancestor:
                return FsTarget(display, display)
            missing.insert(0, os.path.basename(ancestor))
            ancestor = parent

    def resolve_path(self, path: str) -> str:
        return self._resolve_target(path).targetKey

    async def resolve(self, path: str, opts: Optional[Dict[str, Any]] = None) -> FsTarget:
        signal = opts.get("signal") if opts else None
        _throw_if_aborted(signal, "resolve")
        await asyncio.sleep(0)
        result = self._resolve_target(path, opts.get("cwd") if opts else None)
        _throw_if_aborted(signal, "resolve")
        return result

    def processPath(self, target: FsTarget) -> str:
        return target.targetKey

    def process_path(self, target: FsTarget) -> str:
        return self.processPath(target)

    def fileUrl(self, target: FsTarget) -> str:
        return pathlib.Path(target.targetKey).as_uri()

    def file_url(self, target: FsTarget) -> str:
        return self.fileUrl(target)

    def contains(self, parent: Union[FsTarget, str], child: Union[FsTarget, str]) -> bool:
        parent_path = parent.targetKey if isinstance(parent, FsTarget) else self.resolve_path(parent)
        child_path = child.targetKey if isinstance(child, FsTarget) else self.resolve_path(child)
        try:
            relative = os.path.relpath(child_path, parent_path)
        except ValueError:
            return False
        return relative == "." or (relative != ".." and not relative.startswith(".." + os.sep) and not os.path.isabs(relative))

    def _target(self, target: Union[FsTarget, str]) -> FsTarget:
        return target if isinstance(target, FsTarget) else self._resolve_target(target)

    @staticmethod
    def _probe(path: str, follow: bool = True) -> Optional[Tuple[os.stat_result, str]]:
        try:
            native = _native_path(path)
            info = os.stat(native) if follow else os.lstat(native)
        except OSError as error:
            if _is_missing(error):
                return None
            raise
        type_ = "symlink" if not follow and stat_module.S_ISLNK(info.st_mode) else _path_type(info)
        return info, type_

    async def stat(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> Optional[FsInfo]:
        _throw_if_aborted(signal, "stat")
        await asyncio.sleep(0)
        probed = self._probe(self._target(target).targetKey)
        _throw_if_aborted(signal, "stat")
        if probed is None:
            return None
        info, type_ = probed
        return FsInfo(_version_of(info), type_, info.st_size if type_ == "file" else None)

    async def lstat(self, path: str, opts: Optional[Dict[str, Any]] = None, signal: Optional[Any] = None) -> Optional[FsPathInfo]:
        _throw_if_aborted(signal, "lstat")
        if not isinstance(path, str) or not path.strip():
            raise FsError("file_path must be a non-empty string", "FS_NOT_FOUND")
        await asyncio.sleep(0)
        probed = self._probe(self._display_path(path, opts.get("cwd") if opts else None), follow=False)
        _throw_if_aborted(signal, "lstat")
        if probed is None:
            return None
        info, type_ = probed
        return FsPathInfo(_version_of(info), type_, info.st_size)

    def exists(self, path: str) -> bool:
        return _path_exists(self.resolve_path(path))

    def is_file(self, path: str) -> bool:
        probed = self._probe(self.resolve_path(path))
        return probed is not None and probed[1] == "file"

    def is_dir(self, path: str) -> bool:
        probed = self._probe(self.resolve_path(path))
        return probed is not None and probed[1] == "directory"

    def _regular_info(self, target: FsTarget, signal: Optional[Any], verb: str = "read") -> os.stat_result:
        _throw_if_aborted(signal, verb)
        try:
            info = os.stat(_native_path(target.targetKey))
        except OSError as error:
            if _is_missing(error):
                raise FsError('cannot %s "%s": not found' % (verb, target.displayPath), "FS_NOT_FOUND", error)
            raise
        if not stat_module.S_ISREG(info.st_mode):
            raise FsError('cannot %s "%s": not a regular file' % (verb, target.displayPath), "FS_NOT_REGULAR_FILE")
        return info

    def _read_whole_text(self, target: FsTarget, signal: Optional[Any], verb: str = "read") -> str:
        self._regular_info(target, signal, verb)
        with open(_native_path(target.targetKey), "rb") as handle:
            raw = handle.read()
        _throw_if_aborted(signal, verb)
        if b"\x00" in raw[:BINARY_SAMPLE_BYTES]:
            raise FsError('cannot %s "%s": binary file' % (verb, target.displayPath), "FS_NOT_TEXT")
        return _decode_utf8(raw, verb, target.displayPath)

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        target = self._resolve_target(path)
        if encoding.lower().replace("-", "") == "utf8":
            return self._read_whole_text(target, None)
        self._regular_info(target, None)
        with open(_native_path(target.targetKey), "rb") as handle:
            return handle.read().decode(encoding, errors="strict")

    async def readText(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> str:
        local = self._target(target)
        self._regular_info(local, signal)
        await asyncio.sleep(0)
        chunks: List[bytes] = []
        sampled = 0
        with open(_native_path(local.targetKey), "rb") as handle:
            while True:
                _throw_if_aborted(signal, "read")
                raw = handle.read(READ_CHUNK_BYTES)
                if not raw:
                    break
                if sampled < BINARY_SAMPLE_BYTES:
                    sample = raw[:BINARY_SAMPLE_BYTES - sampled]
                    if b"\x00" in sample:
                        raise FsError('cannot read "%s": binary file' % local.displayPath, "FS_NOT_TEXT")
                    sampled += len(sample)
                chunks.append(raw)
                await asyncio.sleep(0)
        _throw_if_aborted(signal, "read")
        return _decode_utf8(b"".join(chunks), "read", local.displayPath)

    async def streamText(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> AsyncIterator[str]:
        local = self._target(target)
        self._regular_info(local, signal)

        async def chunks() -> AsyncIterator[str]:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
            sampled = 0
            with open(_native_path(local.targetKey), "rb") as handle:
                while True:
                    _throw_if_aborted(signal, "read")
                    raw = handle.read(READ_CHUNK_BYTES)
                    if not raw:
                        break
                    if sampled < BINARY_SAMPLE_BYTES:
                        sample = raw[:BINARY_SAMPLE_BYTES - sampled]
                        if b"\x00" in sample:
                            raise FsError('cannot read "%s": binary file' % local.displayPath, "FS_NOT_TEXT")
                        sampled += len(sample)
                    try:
                        yield decoder.decode(raw, final=False)
                    except UnicodeDecodeError as error:
                        raise FsError('cannot read "%s": invalid UTF-8 text' % local.displayPath, "FS_NOT_TEXT", error)
                    await asyncio.sleep(0)
                try:
                    final = decoder.decode(b"", final=True)
                except UnicodeDecodeError as error:
                    raise FsError('cannot read "%s": invalid UTF-8 text' % local.displayPath, "FS_NOT_TEXT", error)
                if final:
                    yield final

        return chunks()

    async def readBytes(self, target: Union[FsTarget, str], signal: Optional[Any] = None, max_bytes: int = 10000000) -> bytes:
        local = self._target(target)
        info = self._regular_info(local, signal)
        if info.st_size > max_bytes:
                raise FsError('cannot read "%s": %s bytes exceeds the %s-byte limit' % (local.displayPath, info.st_size, max_bytes), "FS_TOO_LARGE")
        if self.internals.inspectReadBytesAfterStat is not None:
            await _maybe_await(self.internals.inspectReadBytesAfterStat(local))
        await asyncio.sleep(0)
        chunks: List[bytes] = []
        total = 0
        with open(_native_path(local.targetKey), "rb") as handle:
            while True:
                _throw_if_aborted(signal, "read")
                remaining = max_bytes + 1 - total
                raw = handle.read(min(READ_CHUNK_BYTES, remaining))
                if not raw:
                    break
                chunks.append(raw)
                total += len(raw)
                if total > max_bytes:
                    raise FsError('cannot read "%s": content exceeds the %s-byte limit' % (local.displayPath, max_bytes), "FS_TOO_LARGE")
                await asyncio.sleep(0)
        _throw_if_aborted(signal, "read")
        return b"".join(chunks)

    def write_text(self, path: str, content: str, encoding: str = "utf-8") -> None:
        target = self._resolve_target(path)
        os.makedirs(_native_path(os.path.dirname(target.targetKey)), exist_ok=True)
        with open(_native_path(target.targetKey), "wb") as handle:
            handle.write(content.encode(encoding))

    async def _diff_basis(self, path: str, signal: Optional[Any]) -> Optional[str]:
        _throw_if_aborted(signal, "read")
        try:
            with open(_native_path(path), "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat_module.S_ISREG(info.st_mode) or info.st_size >= self.diff_basis_max_bytes:
                    return None
                chunks: List[bytes] = []
                total = 0
                while total < info.st_size + 1:
                    _throw_if_aborted(signal, "read")
                    raw_chunk = handle.read(min(READ_CHUNK_BYTES, info.st_size + 1 - total))
                    if not raw_chunk:
                        break
                    chunks.append(raw_chunk)
                    total += len(raw_chunk)
                    await asyncio.sleep(0)
                raw = b"".join(chunks)
                if len(raw) != info.st_size or b"\x00" in raw:
                    return None
        except OSError:
            return None
        _throw_if_aborted(signal, "read")
        try:
            return _normalize_line_endings(raw.decode("utf-8", errors="strict"))
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _copy_windows_dacl(source: str, destination: str) -> None:
        import ctypes
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        get_security = advapi32.GetFileSecurityW
        set_security = advapi32.SetFileSecurityW
        get_security.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        get_security.restype = ctypes.c_int
        set_security.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
        set_security.restype = ctypes.c_int
        dacl_information = 0x00000004
        protected_dacl_information = 0x80000000
        needed = ctypes.c_uint32(0)
        source_native = _to_namespaced_path(source)
        destination_native = _to_namespaced_path(destination)
        get_security(source_native, dacl_information, None, 0, ctypes.byref(needed))
        if needed.value == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        descriptor = ctypes.create_string_buffer(needed.value)
        if not get_security(source_native, dacl_information, descriptor, needed.value, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        information = dacl_information | protected_dacl_information
        if not set_security(destination_native, information, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())

    @staticmethod
    def _replace_windows(destination: str, replacement: str) -> None:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        replace_file = kernel32.ReplaceFileW
        replace_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
        replace_file.restype = ctypes.c_int
        if not replace_file(_to_namespaced_path(destination), _to_namespaced_path(replacement), None, 0, None, None):
            code = ctypes.get_last_error()
            if code in (2, 3):
                os.replace(_native_path(replacement), _native_path(destination))
                return
            raise ctypes.WinError(code)

    async def _remove_staging(self, staging: str) -> None:
        if self.internals.removeStagingDir is not None:
            await _maybe_await(self.internals.removeStagingDir(staging))
        else:
            shutil.rmtree(_native_path(staging), ignore_errors=False)

    async def _atomic_write(self, target: FsTarget, content: str, mode: Optional[int], signal: Optional[Any], guarded_create: bool) -> None:
        _throw_if_aborted(signal, "write")
        directory = os.path.dirname(target.targetKey)
        os.makedirs(_native_path(directory), exist_ok=True)
        default_staging_name = ".%s.%s.%s.tmpdir" % (os.path.basename(target.targetKey), os.getpid(), uuid.uuid4().hex)
        staging_name = self.internals.tempDirName(target.targetKey) if self.internals.tempDirName else default_staging_name
        temp_name = self.internals.tempName(target.targetKey) if self.internals.tempName else os.path.basename(target.targetKey) + ".tmp"
        staging = os.path.join(directory, staging_name)
        temp = os.path.join(staging, temp_name)
        created = False
        committed = False
        try:
            os.mkdir(_native_path(staging), 0o700)
            created = True
            if os.name != "nt":
                os.chmod(_native_path(staging), 0o700)
            binary_flag = getattr(os, "O_BINARY", 0)
            descriptor = os.open(_native_path(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL | binary_flag, 0o600)
            try:
                platform = self.internals.platform or ("win32" if os.name == "nt" else os.name)
                if platform == "win32" and mode is not None:
                    copy_dacl = self.internals.copyFileDacl or self._copy_windows_dacl
                    await _maybe_await(copy_dacl(target.targetKey, temp))
                raw = content.encode("utf-8")
                offset = 0
                while offset < len(raw):
                    _throw_if_aborted(signal, "write")
                    end = min(offset + READ_CHUNK_BYTES, len(raw))
                    offset += os.write(descriptor, raw[offset:end])
                    await asyncio.sleep(0)
                os.fsync(descriptor)
                if self.internals.inspectTemp is not None:
                    await _maybe_await(self.internals.inspectTemp({"stagingDir": staging, "tempPath": temp}))
                if mode is not None and os.name != "nt":
                    os.fchmod(descriptor, mode)
            finally:
                os.close(descriptor)
            _throw_if_aborted(signal, "write")
            if guarded_create:
                try:
                    if self.internals.linkFile is not None:
                        await _maybe_await(self.internals.linkFile(temp, target.targetKey))
                    else:
                        os.link(_native_path(temp), _native_path(target.targetKey))
                except OSError as error:
                    current = None
                    try:
                        if self.internals.inspectPublicationTarget is not None:
                            current = await _maybe_await(self.internals.inspectPublicationTarget(target.targetKey))
                        else:
                            current = os.lstat(_native_path(target.targetKey))
                    except OSError as inspect_error:
                        if not _is_missing(inspect_error):
                            raise FsError('cannot write "%s": %s' % (target.displayPath, inspect_error), "FS_IO_ERROR", inspect_error)
                    if current is not None:
                        if not stat_module.S_ISREG(current.st_mode):
                            raise FsError('cannot write "%s": not a regular file' % target.displayPath, "FS_NOT_REGULAR_FILE", error)
                        raise FsError('cannot overwrite existing "%s" without reading it first' % target.displayPath, "FS_NOT_OBSERVED", error)
                    if error.errno == errno.EEXIST:
                        raise FsError('cannot overwrite existing "%s" without reading it first' % target.displayPath, "FS_NOT_OBSERVED", error)
                    raise FsError('cannot write "%s": %s' % (target.displayPath, error), "FS_IO_ERROR", error)
            elif platform == "win32" and mode is not None:
                replace_file = self.internals.replaceFile or self._replace_windows
                try:
                    await _maybe_await(replace_file(target.targetKey, temp))
                except OSError as error:
                    if not _is_missing(error):
                        raise
                    os.replace(_native_path(temp), _native_path(target.targetKey))
            else:
                os.replace(_native_path(temp), _native_path(target.targetKey))
            committed = True
        except BaseException as original:
            if created:
                try:
                    await self._remove_staging(staging)
                except BaseException as cleanup_error:
                    raise FsError("write failed (%s) and temp cleanup failed (%s)" % (original, cleanup_error), "FS_NOT_FOUND", original)
            raise
        if committed and created:
            try:
                await self._remove_staging(staging)
            except BaseException:
                pass

    async def _locked(self, key: str, operation: Any) -> Any:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
            self._lock_users[key] = 0
        self._lock_users[key] += 1
        try:
            async with lock:
                return await operation()
        finally:
            self._lock_users[key] -= 1
            if self._lock_users[key] == 0:
                self._lock_users.pop(key, None)
                if self._locks.get(key) is lock:
                    self._locks.pop(key, None)

    async def writeText(self, target: Union[FsTarget, str], content: str, expected: Optional[Dict[str, Any]] = None,
                        signal: Optional[Any] = None, sandbox_policy: Optional[Any] = None) -> FsWriteOutcome:
        del sandbox_policy
        local = self._target(target)

        async def operation() -> FsWriteOutcome:
            _throw_if_aborted(signal, "write")
            pair = self._probe(local.targetKey)
            existing = pair[0] if pair is not None else None
            if pair is not None and pair[1] != "file":
                raise FsError('cannot write "%s": not a regular file' % local.displayPath, "FS_NOT_REGULAR_FILE")
            kind = expected.get("kind") if isinstance(expected, dict) else None
            if kind == "replaceIfVersion":
                if existing is None:
                    raise FsError('cannot write "%s": file no longer exists' % local.displayPath, "FS_STALE_VERSION")
                if _version_of(existing) != expected.get("version"):
                    raise FsError('cannot write "%s": file changed since it was read' % local.displayPath, "FS_STALE_VERSION")
            elif kind == "createIfAbsent" and existing is not None:
                raise FsError('cannot overwrite existing "%s" without reading it first' % local.displayPath, "FS_NOT_OBSERVED")
            before = None
            if existing is not None and len(content.encode("utf-8")) < self.diff_basis_max_bytes:
                before = await self._diff_basis(local.targetKey, signal)
            mode = stat_module.S_IMODE(existing.st_mode) if existing is not None else None
            await asyncio.sleep(0)
            await self._atomic_write(local, content, mode, signal, kind == "createIfAbsent")
            after = self._probe(local.targetKey)
            version = "missing:%s" % local.targetKey if after is None else _version_of(after[0])
            return FsWriteOutcome("update" if existing is not None else "create", version, before, _normalize_line_endings(content))

        return await self._locked(local.targetKey, operation)

    async def editText(self, target: Union[FsTarget, str], edit: Dict[str, Any], expected: Optional[Dict[str, Any]] = None,
                       signal: Optional[Any] = None, sandbox_policy: Optional[Any] = None) -> FsEditOutcome:
        del sandbox_policy
        local = self._target(target)

        async def operation() -> FsEditOutcome:
            _throw_if_aborted(signal, "edit")
            pair = self._probe(local.targetKey)
            if pair is None:
                raise FsError('cannot edit "%s": file changed since it was read' % local.displayPath, "FS_STALE_VERSION")
            existing, type_ = pair
            if type_ != "file":
                raise FsError('cannot edit "%s": not a regular file' % local.displayPath, "FS_NOT_REGULAR_FILE")
            if expected and _version_of(existing) != expected.get("version"):
                raise FsError('cannot edit "%s": file changed since it was read' % local.displayPath, "FS_STALE_VERSION")
            chunks: List[bytes] = []
            with open(_native_path(local.targetKey), "rb") as handle:
                while True:
                    _throw_if_aborted(signal, "edit")
                    raw_chunk = handle.read(READ_CHUNK_BYTES)
                    if not raw_chunk:
                        break
                    chunks.append(raw_chunk)
                    await asyncio.sleep(0)
            _throw_if_aborted(signal, "edit")
            raw = b"".join(chunks)
            if b"\x00" in raw:
                raise FsError('cannot edit "%s": binary file' % local.displayPath, "FS_NOT_TEXT")
            original = _decode_utf8(raw, "edit", local.displayPath)
            line_endings = _detect_line_endings(original)
            before = _normalize_line_endings(original)
            old = _normalize_line_endings(edit.get("oldString", edit.get("old_str", "")))
            new = _normalize_line_endings(edit.get("newString", edit.get("new_str", "")))
            replace_all = bool(edit.get("replaceAll", edit.get("replace_all", False)))
            if not old:
                raise FsError("old_string must be a non-empty string", "FS_EDIT_NOT_FOUND")
            matches = before.count(old)
            if not matches:
                raise FsError('old_string was not found in "%s"' % local.displayPath, "FS_EDIT_NOT_FOUND")
            if not replace_all and matches > 1:
                raise FsError('old_string matched %s times in "%s"; provide a more specific old_string or set replace_all to true' % (matches, local.displayPath), "FS_AMBIGUOUS_EDIT")
            after = before.replace(old, new) if replace_all else before.replace(old, new, 1)
            await asyncio.sleep(0)
            await self._atomic_write(local, _restore_line_endings(after, line_endings), stat_module.S_IMODE(existing.st_mode), signal, False)
            after_info = self._probe(local.targetKey)
            version = "missing:%s" % local.targetKey if after_info is None else _version_of(after_info[0])
            return FsEditOutcome(version, before, after)

        return await self._locked(local.targetKey, operation)

    async def listDir(self, target: Union[FsTarget, str], signal: Optional[Any] = None) -> List[FsDirEntry]:
        _throw_if_aborted(signal, "list")
        local = self._target(target)
        try:
            pair = self._probe(local.targetKey)
        except OSError as error:
            code = "FS_PERMISSION_DENIED" if _is_permission(error) else "FS_IO_ERROR"
            raise FsError('cannot list "%s": %s' % (local.displayPath, error), code, error)
        if pair is None:
            raise FsError('cannot list "%s": not found' % local.displayPath, "FS_NOT_FOUND")
        if pair[1] != "directory":
            raise FsError('cannot list "%s": not a directory' % local.displayPath, "FS_NOT_DIRECTORY")
        try:
            names = sorted(os.listdir(_native_path(local.targetKey)))
        except OSError as error:
            if _is_missing(error):
                raise FsError('cannot list "%s": not found' % local.displayPath, "FS_NOT_FOUND", error)
            code = "FS_PERMISSION_DENIED" if _is_permission(error) else "FS_IO_ERROR"
            raise FsError('cannot list "%s": %s' % (local.displayPath, error), code, error)
        await asyncio.sleep(0)
        _throw_if_aborted(signal, "list")
        entries: List[FsDirEntry] = []
        for name in names:
            _throw_if_aborted(signal, "list")
            display = os.path.join(local.displayPath, name)
            try:
                identity = self._resolve_target(name, local.targetKey)
                child_target = FsTarget(identity.targetKey, display)
                child = self._probe(child_target.targetKey)
            except OSError as error:
                code = "FS_PERMISSION_DENIED" if _is_permission(error) else "FS_IO_ERROR"
                raise FsError('cannot list "%s": %s' % (display, error), code, error)
            if child is None:
                entries.append(FsDirEntry(name, "other", child_target))
            else:
                info, type_ = child
                entries.append(FsDirEntry(name, type_, child_target, _version_of(info), info.st_size if type_ == "file" else None))
            await asyncio.sleep(0)
        return entries

    def list_dir(self, path: str, max_depth: int = 1) -> List[Dict[str, Any]]:
        del max_depth
        local = self._resolve_target(path)
        probed = self._probe(local.targetKey)
        if probed is None or probed[1] != "directory":
            raise NotADirectoryError("Path is not a directory: %s" % local.targetKey)
        results: List[Dict[str, Any]] = []
        for name in sorted(os.listdir(_native_path(local.targetKey))):
            if name.startswith(".") or name in ("node_modules", "__pycache__", ".venv"):
                continue
            item_path = os.path.join(local.targetKey, name)
            item = self._probe(item_path)
            is_directory = item is not None and item[1] == "directory"
            results.append({"name": name, "path": item_path, "type": "directory" if is_directory else "file",
                            "size": 0 if is_directory else (item[0].st_size if item is not None else 0)})
        return results


class FsLocalPlugin(Plugin):
    id = "fs-local"
    name = PACKAGE_NAME
    version = PACKAGE_VERSION

    def apply(self, ctx: Any) -> None:
        service = FsService(self.config.get("cwd"), self.config.get("diffBasisMaxBytes", DEFAULT_DIFF_BASIS_MAX_BYTES))
        ctx.provide("fs", service)


__all__ = ["PACKAGE_NAME", "PACKAGE_VERSION", "FsError", "FsTarget", "FsInfo", "FsPathInfo", "FsDirEntry",
           "FsWriteOutcome", "FsEditOutcome", "FsIoInternals", "FsConfig", "FsService", "FsLocalPlugin"]
