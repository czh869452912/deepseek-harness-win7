"""Bounded gzip/deflate response decoding shared by native HTTP carriers."""
import zlib


def decompressChunks(chunks, encoding):
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
