import atexit
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import threading


_default = None
_default_lock = threading.Lock()
UCOL_NORMALIZATION_MODE = 4
UCOL_ON = 17
UDATA_NO_FILES = 3
ICU_LIBRARIES = ('dsh_icudt78.dll', 'dsh_icuuc78.dll', 'dsh_icuin78.dll')
ICU_LICENSES = ('ICU-LICENSE', 'LLVM-LICENSE.txt', 'MinGW-COPYING',
                'MinGW-COPYING.MinGW-w64-runtime.txt', 'MinGW-COPYING.MinGW-w64.txt',
                'MinGW-COPYING.winpthreads.txt', 'MinGW-COPYING.winstorecompat.txt')


def verify_icu_files(directory=None):
    directory = Path(directory) if directory is not None else Path(__file__).parent / 'bin' / 'icu'
    directory = directory.resolve()
    manifest = json.loads((directory / 'icu.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise RuntimeError('Pinned ICU manifest is invalid')
    for name, expected in (('version', [78, 2, 0, 0]), ('unicode_version', [17, 0, 0, 0]),
                           ('cldr_version', [48, 0, 0, 0])):
        observed = manifest.get(name)
        if not isinstance(observed, list) or any(type(value) is not int for value in observed) or observed != expected:
            raise RuntimeError('Pinned ICU version differs: ' + name)
    for field, names in (('dll_sha256', ICU_LIBRARIES), ('license_sha256', ICU_LICENSES)):
        hashes = manifest.get(field)
        if not isinstance(hashes, dict) or set(hashes) != set(names):
            raise RuntimeError('Pinned ICU file manifest is incomplete: ' + field)
        if any(not isinstance(value, str) or len(value) != 64 or any(character not in '0123456789abcdef' for character in value)
               for value in hashes.values()):
            raise RuntimeError('Pinned ICU file hash is malformed: ' + field)
    for field, names in (('dll_sha256', ICU_LIBRARIES), ('license_sha256', ICU_LICENSES)):
        hashes = manifest[field]
        for name in names:
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != hashes[name]:
                raise RuntimeError('Pinned ICU file hash differs: ' + name)
    return directory, manifest


class IcuCollator:
    def __init__(self, directory=None, locale=None):
        directory, manifest = verify_icu_files(directory)
        self._directory = directory
        self._manifest = manifest
        names = ICU_LIBRARIES
        self._libraries = [ctypes.CDLL(str(directory / name), winmode=0) for name in names]
        kernel = ctypes.WinDLL('kernel32', winmode=0)
        kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
        kernel.GetModuleFileNameW.restype = ctypes.c_uint32
        for name, library in zip(names, self._libraries):
            loaded = ctypes.create_unicode_buffer(32768)
            length = kernel.GetModuleFileNameW(library._handle, loaded, len(loaded))
            if not length or length >= len(loaded) or os.path.normcase(str(Path(loaded.value).resolve())) != os.path.normcase(str(directory / name)):
                raise RuntimeError('Loaded ICU library path differs: ' + name)
        common, international = self._libraries[1:]
        self._lock = threading.RLock()
        self._handle = None
        common.udata_setCommonData_78.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32)]
        common.udata_setCommonData_78.restype = None
        common.udata_setFileAccess_78.argtypes = [ctypes.c_int32, ctypes.POINTER(ctypes.c_int32)]
        common.udata_setFileAccess_78.restype = None
        self._common_data = ctypes.c_uint8.in_dll(self._libraries[0], 'icudt78_dat')
        status = ctypes.c_int32()
        common.udata_setCommonData_78(ctypes.byref(self._common_data), ctypes.byref(status))
        if status.value > 0:
            raise RuntimeError('Pinned ICU common data registration failed: ' + str(status.value))
        status = ctypes.c_int32()
        common.udata_setFileAccess_78(UDATA_NO_FILES, ctypes.byref(status))
        if status.value > 0:
            raise RuntimeError('Pinned ICU external data refusal failed: ' + str(status.value))
        common.u_getVersion_78.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
        common.u_getVersion_78.restype = None
        common.u_getUnicodeVersion_78.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
        common.u_getUnicodeVersion_78.restype = None
        common.uloc_getDefault_78.argtypes = []
        common.uloc_getDefault_78.restype = ctypes.c_char_p
        version = (ctypes.c_uint8 * 4)()
        common.u_getVersion_78(version)
        if list(version) != manifest['version']:
            raise RuntimeError('Loaded ICU version differs')
        common.u_getUnicodeVersion_78(version)
        if list(version) != manifest['unicode_version']:
            raise RuntimeError('Loaded ICU Unicode version differs')
        international.ulocdata_getCLDRVersion_78.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_int32)]
        international.ulocdata_getCLDRVersion_78.restype = None
        status = ctypes.c_int32()
        international.ulocdata_getCLDRVersion_78(version, ctypes.byref(status))
        if status.value > 0 or list(version) != manifest['cldr_version']:
            raise RuntimeError('Loaded ICU CLDR version differs')
        international.ucol_open_78.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int32)]
        international.ucol_open_78.restype = ctypes.c_void_p
        international.ucol_close_78.argtypes = [ctypes.c_void_p]
        international.ucol_close_78.restype = None
        international.ucol_setAttribute_78.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32,
                                                     ctypes.POINTER(ctypes.c_int32)]
        international.ucol_setAttribute_78.restype = None
        international.ucol_strcoll_78.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16), ctypes.c_int32,
                                                ctypes.POINTER(ctypes.c_uint16), ctypes.c_int32]
        international.ucol_strcoll_78.restype = ctypes.c_int32
        self._international = international
        self.locale = common.uloc_getDefault_78().decode('ascii') if locale is None else locale
        status = ctypes.c_int32()
        handle = international.ucol_open_78(self.locale.replace('-', '_').encode('ascii'), ctypes.byref(status))
        if not handle or status.value > 0:
            if handle:
                international.ucol_close_78(handle)
            raise RuntimeError('Pinned ICU collation initialization failed: ' + str(status.value))
        status = ctypes.c_int32()
        international.ucol_setAttribute_78(handle, UCOL_NORMALIZATION_MODE, UCOL_ON, ctypes.byref(status))
        if status.value > 0:
            international.ucol_close_78(handle)
            raise RuntimeError('Pinned ICU collation normalization failed: ' + str(status.value))
        self._handle = handle

    def runtime_identity(self):
        with self._lock:
            if self._handle is None:
                raise RuntimeError('ICU collator is closed')
            international = self._international
            international.ucol_getAttribute_78.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32)]
            international.ucol_getAttribute_78.restype = ctypes.c_int32
            status = ctypes.c_int32()
            normalization = international.ucol_getAttribute_78(self._handle, UCOL_NORMALIZATION_MODE, ctypes.byref(status))
            if status.value > 0:
                raise RuntimeError('ICU collator attributes could not be read')
            return dict(locale=self.locale, normalization=normalization,
                        version=list(self._manifest['version']), unicodeVersion=list(self._manifest['unicode_version']),
                        cldrVersion=list(self._manifest['cldr_version']), manifest=copy.deepcopy(self._manifest),
                        libraries=[dict(name=name, path=str(self._directory / name),
                                        sha256=hashlib.sha256((self._directory / name).read_bytes()).hexdigest())
                                   for name in ICU_LIBRARIES])

    def compare(self, left, right):
        if not isinstance(left, str) or not isinstance(right, str):
            raise TypeError('ICU collation requires strings')
        def units(value):
            encoded = value.encode('utf-16-le', errors='surrogatepass')
            length = len(encoded) // 2
            if length > 2147483647:
                raise ValueError('ICU collation string exceeds int32 length')
            return (ctypes.c_uint16 * max(1, length)).from_buffer_copy(encoded or b'\0\0'), length
        left_units, left_length = units(left)
        right_units, right_length = units(right)
        with self._lock:
            if self._handle is None:
                raise RuntimeError('ICU collator is closed')
            return self._international.ucol_strcoll_78(self._handle, left_units, left_length, right_units, right_length)

    def close(self):
        with self._lock:
            handle, self._handle = self._handle, None
            if handle is not None:
                self._international.ucol_close_78(handle)

    def __del__(self):
        if getattr(self, '_handle', None) is not None:
            self.close()


def locale_compare(left, right):
    global _default
    with _default_lock:
        if _default is None:
            _default = IcuCollator()
            atexit.register(_default.close)
        collator = _default
    return collator.compare(left, right)

