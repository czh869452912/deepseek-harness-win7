"""Bounded gzip/deflate response decoding shared by native HTTP carriers."""
import zlib
from dsh.host.http_proxy_policy import JS_SPACE


def brotliChunks(chunks):
    import brotli
    decoder = brotli.Decompressor()
    buffered = bytearray()
    for chunk in chunks:
        # Node stops at the first Brotli stream and ignores trailing bytes.
        # Google's binding rejects a call containing both end and trailing data;
        # admit one byte at a time to find the boundary without replay buffers.
        for byte in chunk:
            if decoder.is_finished(): break
            data = bytes([byte])
            while True:
                value = decoder.process(data, output_buffer_limit=16384)
                if value:
                    buffered.extend(value)
                    if len(buffered) >= 32768:
                        yield bytes(buffered); buffered.clear()
                if not value or decoder.is_finished(): break
                data = b''
        if buffered:
            yield bytes(buffered); buffered.clear()
    # Pinned Node uses FLUSH rather than demanding a complete Brotli footer.
    while not decoder.is_finished():
        value = decoder.process(b'', output_buffer_limit=16384)
        if not value: break
        yield value


class _ChunkReader:
    def __init__(self, chunks):
        self.chunks = iter(chunks); self.pending = b''

    def read(self, size):
        if not self.pending:
            try: self.pending = next(self.chunks)
            except StopIteration: return b''
        value, self.pending = self.pending[:size], self.pending[size:]
        return value


def zstdChunks(chunks):
    import zstandard
    reader = _ChunkReader(chunks)
    yield from zstandard.ZstdDecompressor().read_to_iter(reader, read_size=65536, write_size=65536)
    # read_to_iter, like Node, stops at the first frame; finish the wire carrier.
    for _ in reader.chunks: pass


def contentCodings(value):
    codings = value.lower().split(',') if value else []
    if len(codings) > 5:
        raise ValueError('too many content-encodings in response: '+str(len(codings))+', maximum allowed is 5')
    codings = [coding.strip(JS_SPACE) for coding in reversed(codings)]
    return codings if all(coding in ('gzip', 'x-gzip', 'deflate', 'br', 'zstd') for coding in codings) else []


def decodeContentChunks(chunks, codings):
    for coding in codings:
        if coding == 'br': chunks = brotliChunks(chunks)
        elif coding == 'zstd': chunks = zstdChunks(chunks)
        else: chunks = decompressChunks(chunks, 'gzip' if coding == 'x-gzip' else coding)
    return chunks


def decompressChunks(chunks, encoding):
    chunks = iter(chunks)
    decoder = None
    prefix = b''
    for chunk in chunks:
        if decoder is None:
            prefix += chunk
            if len(prefix) < 2:
                continue
            chunk, prefix = prefix, b''
            window = 16+zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS if chunk[0]&15 == 8 else -zlib.MAX_WBITS
            decoder = zlib.decompressobj(window)
        while chunk:
            # A compressed server response must not bypass its consumer's body
            # bound by allocating the entire expanded document in one chunk.
            value = decoder.decompress(chunk, 65536)
            if value:
                yield value
            if decoder.unconsumed_tail and not decoder.eof:
                chunk = decoder.unconsumed_tail
                continue
            chunk = decoder.unused_data
            if decoder.eof and encoding == 'gzip':
                decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
                if chunk.startswith(b'\0'):
                    for _ in chunks: pass
                    return
            elif chunk:
                break
    if decoder is not None:
        value = decoder.flush()
        if value:
            yield value
    elif prefix:
        decoder = zlib.decompressobj(16+zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS)
        value = decoder.decompress(prefix)+decoder.flush()
        if value:
            yield value
