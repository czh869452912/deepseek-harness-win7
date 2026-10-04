import ctypes
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import threading


SQLITE_VERSION = '3.51.2'
SQLITE_SOURCE_ID = '2026-01-09 17:27:48 b270f8339eb13b504d0b2ba154ebca966b7dde08e40c3ed7d559749818cb2075'
SQLITE_DLL_SHA256 = '2339b9e7c8b2d4be67d5516fed37aa70c02bdb463386c47ab130d00586751642'


class DatabaseError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=1)
def _library():
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError('Pinned SQLite requires Windows x64')
    binary = Path(__file__).with_name('bin') / 'sqlite3.dll'
    if hashlib.sha256(binary.read_bytes()).hexdigest() != SQLITE_DLL_SHA256:
        raise RuntimeError('Pinned SQLite DLL hash differs')
    library = ctypes.CDLL(str(binary), winmode=0)
    pointer = ctypes.c_void_p
    integer = ctypes.c_int
    text = ctypes.c_char_p
    signatures = {
        'sqlite3_libversion': (text, []),
        'sqlite3_sourceid': (text, []),
        'sqlite3_open_v2': (integer, [text, ctypes.POINTER(pointer), integer, text]),
        'sqlite3_close': (integer, [pointer]),
        'sqlite3_errmsg': (text, [pointer]),
        'sqlite3_extended_errcode': (integer, [pointer]),
        'sqlite3_exec': (integer, [pointer, text, pointer, pointer, pointer]),
        'sqlite3_prepare_v3': (integer, [pointer, text, integer, ctypes.c_uint,
                                       ctypes.POINTER(pointer), ctypes.POINTER(text)]),
        'sqlite3_finalize': (integer, [pointer]),
        'sqlite3_bind_parameter_count': (integer, [pointer]),
        'sqlite3_bind_null': (integer, [pointer, integer]),
        'sqlite3_bind_int64': (integer, [pointer, integer, ctypes.c_longlong]),
        'sqlite3_bind_double': (integer, [pointer, integer, ctypes.c_double]),
        'sqlite3_bind_text': (integer, [pointer, integer, text, integer, pointer]),
        'sqlite3_bind_blob': (integer, [pointer, integer, pointer, integer, pointer]),
        'sqlite3_step': (integer, [pointer]),
        'sqlite3_column_count': (integer, [pointer]),
        'sqlite3_column_name': (text, [pointer, integer]),
        'sqlite3_column_type': (integer, [pointer, integer]),
        'sqlite3_column_int64': (ctypes.c_longlong, [pointer, integer]),
        'sqlite3_column_double': (ctypes.c_double, [pointer, integer]),
        'sqlite3_column_text': (pointer, [pointer, integer]),
        'sqlite3_column_blob': (pointer, [pointer, integer]),
        'sqlite3_column_bytes': (integer, [pointer, integer]),
        'sqlite3_changes64': (ctypes.c_longlong, [pointer]),
        'sqlite3_last_insert_rowid': (ctypes.c_longlong, [pointer]),
    }
    for name, signature in signatures.items():
        function = getattr(library, name)
        function.restype, function.argtypes = signature
    if (library.sqlite3_libversion().decode('ascii') != SQLITE_VERSION
            or library.sqlite3_sourceid().decode('ascii') != SQLITE_SOURCE_ID):
        raise RuntimeError('Pinned SQLite version/source identity differs')
    return library


class SqliteDatabase:
    def __init__(self, path):
        if not isinstance(path, str) or '\0' in path:
            raise ValueError('SQLite database path must be a NUL-free string')
        self._library = _library()
        self._lock = threading.RLock()
        self._handle = ctypes.c_void_p()
        result = self._library.sqlite3_open_v2(path.encode('utf-8'), ctypes.byref(self._handle), 6, None)
        if result:
            try:
                self._check(result)
            finally:
                if self._handle:
                    self._library.sqlite3_close(self._handle)
                    self._handle = ctypes.c_void_p()

    def _require_open(self):
        if not self._handle:
            raise RuntimeError('SQLite database is closed')

    def _check(self, result):
        if result:
            message = self._library.sqlite3_errmsg(self._handle).decode('utf-8', errors='replace')
            raise DatabaseError(message, self._library.sqlite3_extended_errcode(self._handle))

    def exec(self, sql):
        if not isinstance(sql, str) or '\0' in sql:
            raise ValueError('SQLite SQL must be a NUL-free string')
        with self._lock:
            self._require_open()
            self._check(self._library.sqlite3_exec(self._handle, sql.encode('utf-8'), None, None, None))

    def prepare(self, sql):
        if not isinstance(sql, str) or '\0' in sql:
            raise ValueError('SQLite SQL must be a NUL-free string')
        with self._lock:
            self._require_open()
        return SqliteStatement(self, sql)

    def close(self):
        with self._lock:
            if self._handle:
                self._check(self._library.sqlite3_close(self._handle))
                self._handle = ctypes.c_void_p()

    def _execute(self, sql, parameters, mode):
        with self._lock:
            self._require_open()
            statement = ctypes.c_void_p()
            tail = ctypes.c_char_p()
            encoded = sql.encode('utf-8')
            try:
                self._check(self._library.sqlite3_prepare_v3(self._handle, encoded, len(encoded), 0,
                    ctypes.byref(statement), ctypes.byref(tail)))
                if not statement or (tail.value or b'').strip():
                    raise ValueError('SQLite prepared SQL must contain exactly one statement')
                if self._library.sqlite3_bind_parameter_count(statement) != len(parameters):
                    raise ValueError('SQLite parameter count differs')
                for position, value in enumerate(parameters, 1):
                    self._bind(statement, position, value)
                rows = []
                names = [self._library.sqlite3_column_name(statement, position).decode('utf-8')
                         for position in range(self._library.sqlite3_column_count(statement))]
                while True:
                    result = self._library.sqlite3_step(statement)
                    if result == 101:
                        break
                    if result != 100:
                        self._check(result)
                    if mode != 'run':
                        rows.append({name: self._column(statement, position)
                                     for position, name in enumerate(names)})
                        if mode == 'get':
                            break
                if mode == 'run':
                    return {'changes': self._library.sqlite3_changes64(self._handle),
                            'lastInsertRowid': self._library.sqlite3_last_insert_rowid(self._handle)}
                return (rows[0] if rows else None) if mode == 'get' else rows
            finally:
                if statement:
                    self._library.sqlite3_finalize(statement)

    def _bind(self, statement, position, value):
        library = self._library
        transient = ctypes.c_void_p(-1)
        if value is None:
            result = library.sqlite3_bind_null(statement, position)
        elif isinstance(value, bool):
            raise TypeError('SQLite bindings do not accept booleans')
        elif isinstance(value, int):
            if not -(1 << 63) <= value < (1 << 63):
                raise OverflowError('SQLite integer binding exceeds signed 64-bit range')
            result = library.sqlite3_bind_int64(statement, position, value)
        elif isinstance(value, float):
            result = library.sqlite3_bind_double(statement, position, value)
        elif isinstance(value, str):
            encoded = value.encode('utf-8')
            result = library.sqlite3_bind_text(statement, position, encoded, len(encoded), transient)
        elif isinstance(value, (bytes, bytearray, memoryview)):
            encoded = bytes(value)
            result = library.sqlite3_bind_blob(statement, position, encoded, len(encoded), transient)
        else:
            raise TypeError('SQLite binding type is unsupported')
        self._check(result)

    def _column(self, statement, position):
        library = self._library
        kind = library.sqlite3_column_type(statement, position)
        if kind == 1:
            return library.sqlite3_column_int64(statement, position)
        if kind == 2:
            return library.sqlite3_column_double(statement, position)
        if kind == 5:
            return None
        address = (library.sqlite3_column_text if kind == 3 else library.sqlite3_column_blob)(statement, position)
        value = ctypes.string_at(address, library.sqlite3_column_bytes(statement, position))
        return value.decode('utf-8') if kind == 3 else value


class SqliteStatement:
    def __init__(self, database, sql):
        self._database = database
        self._sql = sql

    def run(self, *parameters):
        return self._database._execute(self._sql, parameters, 'run')

    def get(self, *parameters):
        return self._database._execute(self._sql, parameters, 'get')

    def all(self, *parameters):
        return self._database._execute(self._sql, parameters, 'all')
