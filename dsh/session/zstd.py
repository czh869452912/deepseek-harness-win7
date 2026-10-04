import ctypes
from functools import lru_cache
import hashlib
from pathlib import Path
import json
import os

ROOT = Path(__file__).resolve().parent / 'bin' / 'zstd'
MANIFEST_SHA256 = '692afc72c954be69072be01c242512b201c9f684cdc42e572d109a9fd39e32a8'
DLL_SHA256 = '93d87fd026179637db29580e1db2d1188954241293f0e2279f93a01e007a45cc'


def verify_zstd_files(directory=None):
    directory = Path(directory).resolve() if directory is not None else ROOT.resolve()
    manifest_path = directory / 'zstd.json'
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError('Pinned Zstandard manifest differs')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    hashes = dict(manifest['license_sha256'])
    hashes.update({'dsh_zstd.dll': manifest['dll_sha256'], 'zstd-dictionary.bin': manifest['dictionary_sha256'],
                   'build-provenance.json': manifest['provenance_sha256']})
    for name, expected in hashes.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Pinned Zstandard file differs: ' + name)
    return directory, manifest


class ZstdError(ValueError):
    def __init__(self, message, code=None, name='Error'):
        super().__init__(message)
        self.code = code
        self.name = name


class Input(ctypes.Structure):
    _fields_ = [('src', ctypes.c_void_p), ('size', ctypes.c_size_t), ('pos', ctypes.c_size_t)]


class Output(ctypes.Structure):
    _fields_ = [('dst', ctypes.c_void_p), ('size', ctypes.c_size_t), ('pos', ctypes.c_size_t)]


@lru_cache(maxsize=1)
def library():
    if os.name != 'nt' or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError('Pinned Zstandard requires Windows x64')
    directory, _ = verify_zstd_files()
    binary = directory / 'dsh_zstd.dll'
    loaded = ctypes.CDLL(str(binary), winmode=0)
    kernel = ctypes.WinDLL('kernel32', winmode=0)
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint32
    loaded_path = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(loaded._handle, loaded_path, len(loaded_path))
    if not length or length >= len(loaded_path) or os.path.normcase(str(Path(loaded_path.value).resolve())) != os.path.normcase(str(binary)):
        raise RuntimeError('Loaded Zstandard library path differs')
    pointer, size_type, integer = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
    signatures = {
        'ZSTD_createCCtx': (pointer, []), 'ZSTD_freeCCtx': (size_type, [pointer]),
        'ZSTD_compressBound': (size_type, [size_type]),
        'ZSTD_compress_usingDict': (size_type, [pointer, pointer, size_type, pointer, size_type, pointer, size_type, integer]),
        'ZSTD_createDCtx': (pointer, []), 'ZSTD_freeDCtx': (size_type, [pointer]),
        'ZSTD_DCtx_loadDictionary': (size_type, [pointer, pointer, size_type]),
        'ZSTD_decompressStream': (size_type, [pointer, ctypes.POINTER(Output), ctypes.POINTER(Input)]),
        'ZSTD_isError': (integer, [size_type]), 'ZSTD_getErrorName': (ctypes.c_char_p, [size_type]),
        'ZSTD_getErrorCode': (integer, [size_type]), 'ZSTD_versionString': (ctypes.c_char_p, []),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(loaded, name)
        function.restype, function.argtypes = result, arguments
    if loaded.ZSTD_versionString() != b'1.5.7':
        raise RuntimeError('Loaded Zstandard version differs')
    return loaded


def checked(loaded, value):
    if loaded.ZSTD_isError(value):
        code = loaded.ZSTD_getErrorCode(value)
        names = {10: 'prefix_unknown', 12: 'version_unsupported', 14: 'frameParameter_unsupported',
                 16: 'frameParameter_windowTooLarge', 20: 'corruption_detected', 22: 'checksum_wrong',
                 24: 'literals_headerWrong', 30: 'dictionary_corrupted', 32: 'dictionary_wrong',
                 34: 'dictionaryCreation_failed', 40: 'parameter_unsupported', 41: 'parameter_combination_unsupported',
                 42: 'parameter_outOfBound', 44: 'tableLog_tooLarge', 46: 'maxSymbolValue_tooLarge',
                 48: 'maxSymbolValue_tooSmall', 49: 'cannotProduce_uncompressedBlock',
                 50: 'stabilityCondition_notRespected', 60: 'stage_wrong', 62: 'init_missing',
                 64: 'memory_allocation', 66: 'workSpace_tooSmall', 70: 'dstSize_tooSmall',
                 72: 'srcSize_wrong', 74: 'dstBuffer_null', 80: 'noForwardProgress_destFull',
                 82: 'noForwardProgress_inputEmpty', 100: 'frameIndex_tooLarge', 102: 'seekableIO',
                 104: 'dstBuffer_wrong', 105: 'srcBuffer_wrong', 106: 'sequenceProducer_failed',
                 107: 'externalSequences_invalid'}
        raise ZstdError(loaded.ZSTD_getErrorName(value).decode('utf-8'), 'ZSTD_error_' + names.get(code, str(code)))
    return value


@lru_cache(maxsize=1)
def dictionary():
    directory, _ = verify_zstd_files()
    return (directory / 'zstd-dictionary.bin').read_bytes()


def compress(data):
    loaded = library()
    context = loaded.ZSTD_createCCtx()
    if not context:
        raise MemoryError('Unable to create Zstandard compressor')
    try:
        source = ctypes.create_string_buffer(data)
        raw_dictionary = dictionary()
        dictionary_buffer = ctypes.create_string_buffer(raw_dictionary)
        output = ctypes.create_string_buffer(loaded.ZSTD_compressBound(len(data)))
        count = checked(loaded, loaded.ZSTD_compress_usingDict(context, output, len(output), source,
                        len(data), dictionary_buffer, len(raw_dictionary), 3))
        return output.raw[:count]
    finally:
        checked(loaded, loaded.ZSTD_freeCCtx(context))


def decompress(data, max_output_length=None):
    loaded = library()
    context = loaded.ZSTD_createDCtx()
    if not context:
        raise MemoryError('Unable to create Zstandard decompressor')
    try:
        raw_dictionary = dictionary()
        dictionary_buffer = ctypes.create_string_buffer(raw_dictionary)
        checked(loaded, loaded.ZSTD_DCtx_loadDictionary(context, dictionary_buffer, len(raw_dictionary)))
        source = ctypes.create_string_buffer(data)
        input_data = Input(ctypes.cast(source, ctypes.c_void_p), len(data), 0)
        parts = []
        total = 0
        while input_data.pos < input_data.size:
            capacity = 65536 if max_output_length is None else min(65536, max_output_length - total + 1)
            output_buffer = ctypes.create_string_buffer(capacity)
            output_data = Output(ctypes.cast(output_buffer, ctypes.c_void_p), capacity, 0)
            before = input_data.pos
            remaining = checked(loaded, loaded.ZSTD_decompressStream(context, ctypes.byref(output_data), ctypes.byref(input_data)))
            total += output_data.pos
            if max_output_length is not None and total > max_output_length:
                raise ZstdError('Cannot create a Buffer larger than %d bytes' % max_output_length, 'ERR_BUFFER_TOO_LARGE', 'RangeError')
            parts.append(output_buffer.raw[:output_data.pos])
            if remaining == 0 or (before == input_data.pos and not output_data.pos):
                break
        return b''.join(parts)
    finally:
        checked(loaded, loaded.ZSTD_freeDCtx(context))
