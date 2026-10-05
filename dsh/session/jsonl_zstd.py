import ctypes

from dsh.session.zstd import Input, Output, checked, library


def scan_frames(buffer, max_frames=None):
    frames = []
    offset = 0
    while offset < len(buffer):
        start = offset
        if len(buffer) - offset < 4:
            return dict(frames=frames, tornStart=start)
        if int.from_bytes(buffer[offset:offset + 4], 'little') != 0xFD2FB528:
            raise ValueError('corrupt Zstandard session log: invalid frame magic at byte %s' % offset)
        offset += 4
        if offset == len(buffer):
            return dict(frames=frames, tornStart=start)
        descriptor = buffer[offset]
        offset += 1
        if descriptor & 0x18:
            raise ValueError('corrupt Zstandard session log: reserved frame-header bit at byte %s' % (offset - 1))
        content_flag = descriptor >> 6
        single = bool(descriptor & 0x20)
        checksum = bool(descriptor & 0x04)
        dictionary_flag = descriptor & 0x03
        dictionary_bytes = 4 if dictionary_flag == 3 else dictionary_flag
        content_bytes = (1 if single else 0) if content_flag == 0 else 1 << content_flag
        remaining = (0 if single else 1) + dictionary_bytes + content_bytes
        if len(buffer) - offset < remaining:
            return dict(frames=frames, tornStart=start)
        offset += remaining
        while True:
            if len(buffer) - offset < 3:
                return dict(frames=frames, tornStart=start)
            block = int.from_bytes(buffer[offset:offset + 3], 'little')
            offset += 3
            kind = (block >> 1) & 3
            if kind == 3:
                raise ValueError('corrupt Zstandard session log: reserved block type at byte %s' % (offset - 3))
            payload = 1 if kind == 1 else block >> 3
            if len(buffer) - offset < payload:
                return dict(frames=frames, tornStart=start)
            offset += payload
            if block & 1:
                break
        if checksum:
            if len(buffer) - offset < 4:
                return dict(frames=frames, tornStart=start)
            offset += 4
        frames.append(dict(start=start, end=offset))
        if len(frames) == max_frames:
            return dict(frames=frames)
    return dict(frames=frames)


def compress_frame(data):
    loaded = library()
    context = loaded.ZSTD_createCCtx()
    if not context:
        raise MemoryError('Unable to create Zstandard compressor')
    try:
        checked(loaded, loaded.ZSTD_CCtx_setParameter(context, 201, 1))
        source = ctypes.create_string_buffer(data)
        incoming = Input(ctypes.cast(source, ctypes.c_void_p), len(data), 0)
        parts = []
        first = True
        while first or incoming.pos < incoming.size:
            first = False
            target = ctypes.create_string_buffer(65536)
            outgoing = Output(ctypes.cast(target, ctypes.c_void_p), len(target), 0)
            checked(loaded, loaded.ZSTD_compressStream2(context, ctypes.byref(outgoing), ctypes.byref(incoming), 0))
            parts.append(target.raw[:outgoing.pos])
        while True:
            target = ctypes.create_string_buffer(65536)
            outgoing = Output(ctypes.cast(target, ctypes.c_void_p), len(target), 0)
            remaining = checked(loaded, loaded.ZSTD_compressStream2(context, ctypes.byref(outgoing), ctypes.byref(incoming), 2))
            parts.append(target.raw[:outgoing.pos])
            if remaining == 0:
                return b''.join(parts)
    finally:
        checked(loaded, loaded.ZSTD_freeCCtx(context))


def decompress_frame(data, incomplete=False):
    loaded = library()
    context = loaded.ZSTD_createDCtx()
    if not context:
        raise MemoryError('Unable to create Zstandard decompressor')
    try:
        source = ctypes.create_string_buffer(data)
        incoming = Input(ctypes.cast(source, ctypes.c_void_p), len(data), 0)
        parts = []
        while True:
            target = ctypes.create_string_buffer(65536)
            outgoing = Output(ctypes.cast(target, ctypes.c_void_p), len(target), 0)
            before = incoming.pos
            remaining = checked(loaded, loaded.ZSTD_decompressStream(context, ctypes.byref(outgoing), ctypes.byref(incoming)))
            parts.append(target.raw[:outgoing.pos])
            if remaining == 0:
                return b''.join(parts)
            if incoming.pos == incoming.size and outgoing.pos < outgoing.size:
                if incomplete:
                    return b''.join(parts)
                raise ValueError('unexpected end of Zstandard frame')
            if before == incoming.pos and outgoing.pos == 0:
                raise ValueError('Zstandard decoder made no progress')
    finally:
        checked(loaded, loaded.ZSTD_freeDCtx(context))
