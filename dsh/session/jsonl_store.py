import asyncio
import functools
import os
import tempfile
import time

from dsh.cordis.json_text import stringify_json
from dsh.session.durable_publish import ensure_durable_directory, publish_new_file, discard_staging
from dsh.session.file_revision import file_revision
from dsh.session.persistence import SessionFormatUnsupportedError, SessionLocation
from dsh.session.preparations import throw_aborted
from dsh.session.jsonl_format import SessionLogScanner, encode_segment, project_key, header_bytes, event_bytes, parse_header_meta, scan_log
from dsh.session.jsonl_zstd import compress_frame, decompress_frame, scan_frames


class JsonlRollbackError(RuntimeError):
    name = 'AggregateError'

    def __init__(self, path, original, rollback):
        super().__init__('failed to roll back append to "%s"' % path)
        self.errors = [original, rollback]


class JsonlStore:
    def __init__(self, root, compression='zstd', pack_chunks=True):
        self.root = os.path.abspath(root)
        self.compression = compression
        self.pack_chunks = pack_chunks
        self.root_checked = False
        self.root_error = None
        try:
            with os.scandir(self.root):
                pass
        except FileNotFoundError:
            pass

    def suffix(self, opposite=False):
        compressed = self.compression == 'zstd'
        if opposite:
            compressed = not compressed
        return '.jsonl.zstd' if compressed else '.jsonl'

    def locate(self, meta, opposite=False):
        project = '_no-cwd' if meta.get('cwd') is None else project_key(meta['cwd'])
        return os.path.join(self.root, project, encode_segment(meta['id']), 'session' + self.suffix(opposite))

    def _encoding_error(self, path):
        return ValueError('session artifact %s uses %s, but this backend is configured for compression %s; use a separate root or select the matching compression mode'
            % (stringify_json(path), self.suffix(True), stringify_json(self.compression)))

    def _legacy_error(self, path):
        return ValueError('session artifact %s uses the unsupported flat-file layout; use a separate root or move it into a project/session directory before loading'
            % stringify_json(path))

    def _exists(self, path):
        try:
            with open(path, 'rb'):
                return True
        except FileNotFoundError:
            parent = os.path.dirname(path)
            try:
                with os.scandir(parent):
                    pass
            except FileNotFoundError:
                pass
            return False

    def _projects(self):
        try:
            with os.scandir(self.root) as entries:
                return [entry.path for entry in entries if entry.is_dir(follow_symlinks=False)]
        except FileNotFoundError:
            return []

    def _sessions(self, project):
        with os.scandir(project) as entries:
            entries = list(entries)
        for entry in entries:
            if entry.is_file(follow_symlinks=False) and (entry.name.endswith('.jsonl') or entry.name.endswith('.jsonl.zstd')):
                raise self._legacy_error(entry.path)
        return [entry.path for entry in entries if entry.is_dir(follow_symlinks=False)]

    def _ensure_encoding(self):
        if self.root_checked:
            if self.root_error is not None:
                raise self.root_error
            return
        self.root_checked = True
        try:
            for project in self._projects():
                for directory in self._sessions(project):
                    incompatible = os.path.join(directory, 'session' + self.suffix(True))
                    if self._exists(incompatible):
                        raise self._encoding_error(incompatible)
        except BaseException as error:
            self.root_error = error
            raise

    def find(self, identity):
        self._ensure_encoding()
        matches = []
        encoded = encode_segment(identity)
        for project in self._projects():
            for suffix in ('.jsonl.zstd', '.jsonl'):
                legacy = os.path.join(project, encoded + suffix)
                if self._exists(legacy):
                    raise self._legacy_error(legacy)
            directory = os.path.join(project, encoded)
            opposite = os.path.join(directory, 'session' + self.suffix(True))
            if self._exists(opposite):
                raise self._encoding_error(opposite)
            path = os.path.join(directory, 'session' + self.suffix())
            if self._exists(path):
                matches.append(path)
        if len(matches) > 1:
            raise ValueError('duplicate JSONL session id "%s" appears in multiple project directories' % identity)
        return matches[0] if matches else None

    def _identity(self, path, meta, identity=None):
        if identity is not None and meta.id != identity:
            raise ValueError('corrupt session log "%s": requested id "%s" does not match header id "%s"' % (path, identity, meta.id))
        try:
            expected = self.locate(meta.to_dict())
        except Exception as error:
            raise ValueError('corrupt session log "%s": header id cannot name a storage path' % path) from error
        if path != expected:
            try:
                matches = os.path.samefile(path, expected)
            except FileNotFoundError:
                matches = False
            if not matches:
                raise ValueError('corrupt session log "%s": header id "%s" and cwd identify "%s"' % (path, meta.id, expected))

    async def read_stable(self, path, signal=None):
        while True:
            throw_aborted(signal)
            buffer, before, after = await self._run(self._read_file, path, signal)
            throw_aborted(signal)
            if before == after:
                return buffer, after
            await asyncio.sleep(0)

    async def _run(self, operation, *arguments):
        pending = asyncio.get_running_loop().run_in_executor(None, functools.partial(operation, *arguments))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            await asyncio.gather(pending, return_exceptions=True)
            raise

    def _read_file(self, path, signal):
        throw_aborted(signal)
        before = file_revision(path)
        parts = []
        with open(path, 'rb') as stream:
            while True:
                throw_aborted(signal)
                chunk = stream.read(65536)
                if not chunk:
                    break
                parts.append(chunk)
        throw_aborted(signal)
        return b''.join(parts), before, file_revision(path)

    def _header_frame(self, plaintext):
        if not plaintext or plaintext.find(b'\n') != len(plaintext) - 1:
            raise ValueError('corrupt Zstandard session log: first frame is not exactly one header line')

    async def _scan_zstd(self, buffer, signal=None):
        throw_aborted(signal)
        structural = scan_frames(buffer)
        frames = structural['frames']
        if not frames:
            raise ValueError('empty or header-less Zstandard session log')
        first = frames[0]
        header = self._decode(buffer, first)
        self._header_frame(header)
        scanner = SessionLogScanner(header)
        deadline = time.monotonic() + 0.5
        for index, frame in enumerate(frames[1:]):
            throw_aborted(signal)
            scanner.write(self._decode(buffer, frame))
            if index + 2 < len(frames) and time.monotonic() >= deadline:
                await asyncio.sleep(0)
                throw_aborted(signal)
                deadline = time.monotonic() + 0.5
        throw_aborted(signal)
        checkpoint = scanner.checkpoint()
        if checkpoint['committedBytes'] != checkpoint['inputBytes']:
            raise ValueError('corrupt Zstandard session log: complete frame contains a torn JSONL record')
        if 'tornStart' not in structural:
            return scanner.finish()
        torn = structural['tornStart']
        try:
            recovered = decompress_frame(buffer[torn:], incomplete=True)
        except Exception:
            throw_aborted(signal)
            recovered = b''
        throw_aborted(signal)
        scanner.write(recovered)
        prefix = scanner.finish()
        prefix['tornMarker'] = dict(truncateTo=torn, recoveredEvents=prefix['events'][checkpoint['eventCount']:])
        return prefix

    def _decode(self, buffer, frame):
        try:
            return decompress_frame(buffer[frame['start']:frame['end']])
        except Exception as error:
            raise ValueError('corrupt Zstandard session log: frame at byte %s failed validation' % frame['start']) from error

    async def load_stored(self, identity, signal=None):
        throw_aborted(signal)
        path = self.find(identity)
        if path is None:
            return None
        buffer, revision = await self.read_stable(path, signal)
        try:
            if self.compression == 'zstd':
                prefix = await self._scan_zstd(buffer, signal)
            else:
                prefix = scan_log(buffer)
                if prefix['committedBytes'] < len(buffer):
                    prefix['tornMarker'] = dict(truncateTo=prefix['committedBytes'], recoveredEvents=[])
        except SessionFormatUnsupportedError as error:
            failure = SessionFormatUnsupportedError(str(error) + ' (raw log: ' + path + ')')
            failure.location = SessionLocation('jsonl', path)
            raise failure from error
        throw_aborted(signal)
        self._identity(path, prefix['meta'], identity)
        prefix.update(meta=prefix['meta'].to_dict(), revision=revision)
        return prefix

    async def read_revision(self, identity, signal=None):
        throw_aborted(signal)
        path = self.find(identity)
        if path is None:
            return None
        try:
            revision = file_revision(path)
            throw_aborted(signal)
            return revision
        except FileNotFoundError:
            return None

    async def materialize_header(self, meta):
        await self.append_batch(meta, [], False)

    async def append_batch(self, meta, events, materialized):
        await self._run(self._append_batch, meta, events, materialized)

    def _append_batch(self, meta, events, materialized):
        self._ensure_encoding()
        path = self.locate(meta)
        if materialized:
            if events:
                self._append(path, self._event_frame(events))
            return
        opposite = self.locate(meta, True)
        if self._exists(opposite):
            raise self._encoding_error(opposite)
        from dsh.session.sqlite_logical import header_from_stored
        header = header_bytes(header_from_stored(meta))
        content = compress_frame(header) if self.compression == 'zstd' else header
        if events:
            content += self._event_frame(events)
        directory = os.path.dirname(path)
        ensure_durable_directory(directory)
        if self._exists(path):
            raise ValueError('session "%s" already has a persisted log; refusing to overwrite it' % meta['id'])
        descriptor, staging = tempfile.mkstemp(prefix='.session-', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            publish_new_file(staging, path)
        finally:
            discard_staging(staging)

    def _event_frame(self, events):
        plaintext = event_bytes(events, self.pack_chunks)
        return compress_frame(plaintext) if self.compression == 'zstd' else plaintext

    def _append(self, path, content):
        before = os.stat(path).st_size
        try:
            with open(path, 'ab', buffering=0) as stream:
                remaining = memoryview(content)
                while remaining:
                    count = stream.write(remaining)
                    if not count:
                        raise OSError('session append made no progress')
                    remaining = remaining[count:]
                os.fsync(stream.fileno())
        except BaseException as error:
            try:
                self._truncate(path, before)
            except BaseException as rollback:
                raise JsonlRollbackError(path, error, rollback) from error
            raise

    def _truncate(self, path, size):
        with open(path, 'r+b') as stream:
            stream.truncate(size)
            stream.flush()
            os.fsync(stream.fileno())

    async def commit_repair(self, meta, marker, closers):
        await self._run(self._commit_repair, meta, marker, closers)

    def _commit_repair(self, meta, marker, closers):
        path = self.locate(meta)
        if marker is not None:
            self._truncate(path, marker['truncateTo'])
        recovered = (marker['recoveredEvents'] if marker is not None else []) + closers
        if recovered:
            self._append(path, self._event_frame(recovered))

    def _first_line(self, path):
        with open(path, 'rb') as stream:
            if self.compression == 'none':
                parts = []
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        return None
                    boundary = chunk.find(b'\n')
                    parts.append(chunk if boundary < 0 else chunk[:boundary])
                    if boundary >= 0:
                        return b''.join(parts).decode('utf-8', 'replace')
            content = bytearray()
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return None
                content.extend(chunk)
                first = scan_frames(content, 1)['frames']
                if not first:
                    continue
                try:
                    decoded = decompress_frame(bytes(content[first[0]['start']:first[0]['end']]))
                except Exception as error:
                    raise ValueError('corrupt Zstandard session log: header frame failed validation') from error
                self._header_frame(decoded)
                return decoded[:-1].decode('utf-8', 'replace')

    async def list(self, signal=None):
        throw_aborted(signal)
        self._ensure_encoding()
        headers = []
        identities = set()
        for project in self._projects():
            for directory in self._sessions(project):
                throw_aborted(signal)
                opposite = os.path.join(directory, 'session' + self.suffix(True))
                if self._exists(opposite):
                    raise self._encoding_error(opposite)
                path = os.path.join(directory, 'session' + self.suffix())
                if not self._exists(path):
                    continue
                first = self._first_line(path)
                metadata = parse_header_meta(first) if first is not None else None
                if metadata is None:
                    continue
                self._identity(path, metadata)
                if metadata.id in identities:
                    raise ValueError('duplicate JSONL session id "%s" appears in multiple project directories' % metadata.id)
                identities.add(metadata.id)
                headers.append(metadata.to_dict())
        throw_aborted(signal)
        return headers

    async def list_snapshots(self, signal=None):
        snapshots = []
        for metadata in await self.list(signal):
            throw_aborted(signal)
            try:
                snapshots.append(dict(header=metadata, revision=file_revision(self.locate(metadata))))
            except FileNotFoundError:
                pass
        throw_aborted(signal)
        return snapshots

    async def read_raw(self, identity, signal=None):
        throw_aborted(signal)
        path = self.find(identity)
        if path is None:
            return None
        buffer, revision = await self.read_stable(path, signal)
        if self.compression == 'zstd':
            frames = scan_frames(buffer)['frames']
            if not frames:
                raise ValueError('empty or header-less Zstandard session log')
            pieces = []
            for frame in frames:
                throw_aborted(signal)
                pieces.append(self._decode(buffer, frame))
            buffer = b''.join(pieces)
        content = buffer.decode('utf-8', 'replace')
        metadata = parse_header_meta(content.split('\n', 1)[0])
        if metadata is None or metadata.id != identity:
            raise ValueError('corrupt session log: invalid header line in "%s"' % path)
        return dict(meta=metadata, filename='session.jsonl', content=content)

    async def close(self):
        pass
