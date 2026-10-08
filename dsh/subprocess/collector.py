"""
Bounded output stream collector with spill recovery.
1:1 parity with OutputCollector in @deepseek-ai/dsh-subprocess-local/spawn.ts
Python 3.8.10 compatible.
"""

import codecs
import os
import random
import string
import tempfile
from typing import Dict, List, Optional

from dsh.subprocess.types import CollectedOutput, SubprocessOutputRead, SubprocessOutputReader

_spill_counter = 0
_default_spill_dir: Optional[str] = None


def _private_spill_dir() -> str:
    global _default_spill_dir
    if _default_spill_dir is None:
        _default_spill_dir = tempfile.mkdtemp(prefix="dsh-subprocess-")
    return _default_spill_dir


class OutputCollector(SubprocessOutputReader):
    """Collects one stream with a bounded in-memory tail and optional spill file."""

    def __init__(
        self,
        max_bytes: int,
        max_spill_bytes: Optional[int],
        label: str,
        spill_dir: Optional[str] = None,
        text_encoding: str = 'utf-8',
    ):
        self.max_bytes = max_bytes
        self.max_spill_bytes = max_spill_bytes
        self.label = label
        self.spill_dir = spill_dir or _private_spill_dir()
        self.text_encoding = text_encoding
        self._detected_encoding = None
        self._encoding_prefix = b''
        self._sealed = False

        self.chunks: List[bytes] = []
        self.bytes_count = 0
        self.dropped = False
        self.spill_fd: Optional[int] = None
        self.spill_file: Optional[str] = None
        self.spill_disabled = max_spill_bytes is None
        self.total = 0

    def push(self, chunk: bytes) -> None:
        if not chunk:
            return
        if self.text_encoding == 'powershell' and len(self._encoding_prefix) < 8:
            self._encoding_prefix = (self._encoding_prefix + chunk)[:8]
            prefix = self._encoding_prefix
            if prefix.startswith(codecs.BOM_UTF16_LE):
                self._detected_encoding = 'utf-16-le'
            elif prefix.startswith(codecs.BOM_UTF16_BE):
                self._detected_encoding = 'utf-16-be'
            elif len(prefix) == 8 and prefix[1:8:2] == b'\0\0\0\0' and all(prefix[0:8:2]):
                self._detected_encoding = 'utf-16-le'
        self.total += len(chunk)
        overflows = (self.bytes_count + len(chunk)) > self.max_bytes

        if not self.spill_disabled and (overflows or self.spill_fd is not None):
            self._spill_all(chunk)

        self.chunks.append(chunk)
        self.bytes_count += len(chunk)

        while self.bytes_count > self.max_bytes:
            head = self.chunks[0]
            excess = self.bytes_count - self.max_bytes
            if len(head) <= excess:
                self.chunks.pop(0)
                self.bytes_count -= len(head)
            else:
                self.chunks[0] = head[excess:]
                self.bytes_count -= excess
            self.dropped = True

    def _spill_all(self, chunk: bytes) -> None:
        if self.max_spill_bytes is not None and self.total > self.max_spill_bytes:
            self._discard_spill()
            return

        if self.spill_fd is None:
            global _spill_counter
            _spill_counter += 1
            rand_suffix = "".join(random.choices(string.hexdigits.lower(), k=12))
            filename = f"dsh-subprocess-{os.getpid()}-{_spill_counter}-{rand_suffix}-{self.label}.log"
            self.spill_file = os.path.join(self.spill_dir, filename)

            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY

            try:
                self.spill_fd = os.open(self.spill_file, flags, 0o600)
                for prior in self.chunks:
                    os.write(self.spill_fd, prior)
            except Exception:
                self._discard_spill()
                return

        if self.spill_fd is not None:
            try:
                os.write(self.spill_fd, chunk)
            except Exception:
                self._discard_spill()

    def _discard_spill(self) -> None:
        fd = self.spill_fd
        sf = self.spill_file
        self.spill_fd = None
        self.spill_file = None
        self.spill_disabled = True
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if sf is not None:
            try:
                os.remove(sf)
            except Exception:
                pass

    def read_from(self, from_byte: int) -> SubprocessOutputRead:
        window_start = self.total - self.bytes_count
        buffer_data = b"".join(self.chunks)
        lossy = from_byte < window_start
        if lossy:
            slice_data = buffer_data
        else:
            offset_in_buf = from_byte - window_start
            slice_data = buffer_data[offset_in_buf:]

        next_offset = self.total
        if self.text_encoding == 'powershell':
            if self._detected_encoding is None and window_start == 0 and len(buffer_data) < 8 and not self._sealed:
                return SubprocessOutputRead(text='', next_offset=0, lossy=lossy, spill_path=self.spill_file)
            encoding = self._detected_encoding or 'utf-8'
            undecodable = False
            try:
                probe = codecs.getincrementaldecoder(encoding)(errors='strict')
                probe.decode(buffer_data, final=self._sealed)
            except UnicodeError:
                undecodable = True
            if (self._detected_encoding or undecodable) and not self.spill_disabled and self.spill_fd is None and self.spill_file is None:
                self._spill_all(b'')
                if self._sealed:
                    self.seal()
            if self._detected_encoding:
                # Retain raw startup diagnostics even when the memory cap was
                # not reached; a text rendering must never be the only copy.
                if (self.total - len(slice_data)) % 2:
                    slice_data = slice_data[1:]
                    lossy = True
                if self.total - len(slice_data) == 0 and slice_data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                    slice_data = slice_data[2:]
            decoder = codecs.getincrementaldecoder(encoding)(errors='backslashreplace')
            text = decoder.decode(slice_data, final=self._sealed)
            next_offset -= len(decoder.getstate()[0])
        else:
            text = slice_data.decode("utf-8", errors="replace")
        return SubprocessOutputRead(
            text=text,
            next_offset=next_offset,
            lossy=lossy,
            spill_path=self.spill_file,
        )

    def seal(self) -> None:
        self._sealed = True
        if self.spill_fd is None:
            return
        try:
            os.close(self.spill_fd)
        except Exception:
            self.spill_file = None
        self.spill_fd = None

    def finalize(self) -> CollectedOutput:
        self.seal()
        text = self.read_from(0).text if self.text_encoding == 'powershell' else b"".join(self.chunks).decode("utf-8", errors="replace")
        # read_from may have created the raw diagnostic spill after seal.
        self.seal()
        return CollectedOutput(
            text=text,
            truncated=self.dropped,
            spill_path=self.spill_file,
        )
