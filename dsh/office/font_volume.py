"""Physical font ownership for the SDK's explicit private memory volume."""
import errno
import hashlib
import os
import stat

from .errors import OfficeKitError
from .outputs import _native


EXTENSIONS = frozenset(('.ttf', '.otf', '.ttc', '.otc', '.dfont'))
ABSENT = frozenset((errno.ENOENT, errno.EACCES, errno.EPERM, errno.ENOTDIR))
CHANGED = 'A system font changed during conversion; retry the operation.'


def _fstat(descriptor):
    info = os.fstat(descriptor)
    if os.name == 'nt':
        from dsh.fs.win32_stat import node_fstat
        info = node_fstat(descriptor, info)
    return info


def _lstat(path):
    info = os.lstat(_native(path))
    if os.name == 'nt':
        from dsh.fs.win32_stat import node_stat
        info = node_stat(_native(path), info, follow=False)
    return info


def identity(info):
    return dict(dev=str(info.st_dev), ino=str(info.st_ino), size=info.st_size,
                mtimeNs=str(info.st_mtime_ns), ctimeNs=str(info.st_ctime_ns))


def _changed(cause=None):
    return OfficeKitError('failed', CHANGED, cause=cause)


class _Read:
    def __init__(self, asset):
        self.asset = asset
        self.stream = None
        self.read_bytes = 0

    def __enter__(self):
        try:
            self.stream = open(_native(self.asset.path), 'rb')
            info = _fstat(self.stream.fileno())
            if not stat.S_ISREG(info.st_mode) or identity(info) != self.asset.expected:
                raise _changed()
            if info.st_size > self.asset.maximum:
                raise OfficeKitError('failed', 'The font exceeds maxFontFileBytes.')
            return self
        except BaseException as cause:
            if self.stream is not None:
                self.stream.close()
            if isinstance(cause, OSError):
                raise _changed(cause) from None
            raise

    def fileno(self):
        return self.stream.fileno()

    def read(self, size):
        # Bounded independently of the browser's request or declared font metadata.
        remaining = min(self.asset.expected['size'], self.asset.maximum) - self.read_bytes
        if size < 0:
            size = remaining + 1
        data = self.stream.read(min(size, remaining + 1))
        self.read_bytes += len(data)
        if self.read_bytes > self.asset.expected['size'] or self.read_bytes > self.asset.maximum:
            raise _changed()
        if not data and self.read_bytes != self.asset.expected['size']:
            raise _changed()
        return data

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                if identity(_fstat(self.stream.fileno())) != self.asset.expected:
                    raise _changed()
                self.asset.validate()
        finally:
            self.stream.close()


class FontAsset:
    def __init__(self, path, expected, maximum):
        self.path, self.expected, self.maximum = path, expected, maximum

    def open(self, mode):
        if mode != 'rb':
            raise ValueError('The font volume is read-only.')
        return _Read(self)

    def validate(self):
        try:
            info = _lstat(self.path)
            if not stat.S_ISREG(info.st_mode) or identity(info) != self.expected:
                raise _changed()
        except OSError as cause:
            raise _changed(cause) from None


class FontVolume:
    """Enumerate exact files; leave parsing/glyph selection to the original SDK.

    Virtual names retain the original canonical path after one constant prefix,
    so SDK localeCompare tie ordering retains the physical path characters.
    HTTP names are opaque and never grant access to a directory or raw path.
    """
    def __init__(self, directories, *, max_files=20000, max_file_bytes=268435456, check=None, include_directories=False):
        self.assets, self.files, self.sources = {}, {}, {}
        self.directories = {}
        self.paths = []
        visited = set()
        pending = list(reversed(directories))
        while pending:
            if check is not None:
                check()
            path = pending.pop()
            try:
                canonical = os.path.realpath(os.path.abspath(path))
                info = _lstat(canonical)
            except OSError as error:
                if error.errno in ABSENT:
                    continue
                raise
            if canonical in visited:
                continue
            visited.add(canonical)
            if stat.S_ISDIR(info.st_mode):
                try:
                    names = os.listdir(_native(canonical))
                except OSError as error:
                    if error.errno in ABSENT:
                        continue
                    raise
                if include_directories:
                    entries = []
                    for name in names:
                        try:
                            child = _lstat(os.path.join(canonical, name))
                        except OSError as error:
                            if error.errno in ABSENT:
                                continue
                            raise
                        kind = 'directory' if stat.S_ISDIR(child.st_mode) else 'file' if stat.S_ISREG(child.st_mode) else 'other'
                        entries.append(dict(name=name, kind=kind))
                    self.directories['/physical/' + canonical] = entries
                pending.extend(os.path.join(canonical, name) for name in sorted(
                    names, key=lambda value: value.encode('utf-16-be', 'surrogatepass'), reverse=True))
            elif stat.S_ISREG(info.st_mode) and os.path.splitext(canonical)[1].lower() in EXTENSIONS:
                if len(self.paths) >= max_files:
                    raise OfficeKitError('failed', 'The system font catalog exceeds maxFontFiles.')
                virtual = '/physical/' + canonical
                route = 'font-' + hashlib.sha256(canonical.encode('utf-8', 'surrogatepass')).hexdigest() + os.path.splitext(canonical)[1].lower()
                expected = identity(info)
                self.assets[route] = FontAsset(canonical, expected, max_file_bytes)
                self.files[virtual] = dict(route=route, identity=expected)
                self.sources[virtual] = self.assets[route]
                self.paths.append(virtual)

    def manifest(self):
        return dict(files=self.files, directories=self.directories)

    def validate(self, records):
        for record in records:
            source = self.sources.get(record['path'])
            if source is None:
                raise OfficeKitError('failed', 'The font snapshot references an unknown source.')
            source.validate()
