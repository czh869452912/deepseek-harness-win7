"""Immutable historical generations and exclusive durable current publication."""
import asyncio
import hashlib
import inspect
import os
import secrets
import stat
import time

from dsh.core.session.json import UNDEFINED
from dsh.cordis.json_text import stringify_json
from dsh.llm.assistant_stream import expandAssistantStream
from dsh.llm.assembler import BlockAssembler
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError
from dsh.session.format.chain import call, member
from dsh.session.format_v0_to_v1.payload import equal_json
from dsh.session.format_v2_to_v3.payload import display
from dsh.session.format_catalog import sessionFormatCatalog
from dsh.session.format_catalog.current import validateInstalledCurrentSessionArtifact
from dsh.session.file_io import filesystem_path, open_shared_read
from dsh.session.file_revision import filesystem_identity
from dsh.session.durable_publish import publish_new_file
from dsh.session.jsonl_current import generationLogFilename, logSuffix, SessionLogScanner
from dsh.session.jsonl_zstd import compress_frame, decompress_frame, scan_frames
from dsh.session.preparations import throw_aborted
from dsh.session.sqlite_json import parse_json

IDENTITY_FIELDS = ('dev', 'ino', 'size', 'mtimeNs', 'ctimeNs')


class JsonlGenerationSourceChangedError(ValueError):
    name = 'JsonlGenerationSourceChangedError'

    def __init__(self, path):
        super().__init__('historical session generation changed during migration: "%s"' % path)
        self.path = path


class JsonlGenerationUnsupportedMigrationError(ValueError):
    name = 'JsonlGenerationUnsupportedMigrationError'

    def __init__(self, version, reason):
        super().__init__(str(reason))
        self.fromVersion, self.reason, self.cause = version, reason, reason


class JsonlGenerationTargetConflictError(ValueError):
    name = 'JsonlGenerationTargetConflictError'

    def __init__(self, path, reason):
        super().__init__('current session generation already exists at "%s": %s' % (path, reason))
        self.path, self.reason, self.cause = path, reason, reason


class GenerationAggregateError(ValueError):
    name = 'AggregateError'

    def __init__(self, errors, message):
        super().__init__(message)
        self.errors = errors


async def resolved(value):
    return await value if inspect.isawaitable(value) else value


def identity(value):
    return tuple(value[key] for key in IDENTITY_FIELDS)


def read_bytes(path):
    with open_shared_read(path) as file:
        return file.read()


def stringifyJson(value, subject):
    try:
        return stringify_json(value)
    except Exception as error:
        failure = ValueError(subject + ' is not lossless JSON')
        if value is not UNDEFINED:
            failure.cause = error
        raise failure from error


class NativeGenerationFileSystem:
    def stat(self, path):
        return filesystem_identity(path)

    def readFile(self, path, signal=None):
        throw_aborted(signal)
        return read_bytes(path)

    def readdir(self, path):
        return os.listdir(filesystem_path(path))

    def lstat(self, path):
        return os.lstat(filesystem_path(path))

    def rm(self, path):
        os.unlink(filesystem_path(path))

    def open(self, path, flags, mode=0o600):
        descriptor = os.open(filesystem_path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), mode)
        return os.fdopen(descriptor, 'wb')


class MigratingJsonlRows:
    def __init__(self, restore):
        self.restore, self.fragments, self.row_index, self.issue = restore, bytearray(), 0, None

    def write(self, chunk):
        offset = 0
        while True:
            end = chunk.find(b'\n', offset)
            if end < 0:
                self.fragments.extend(chunk[offset:])
                return
            self.fragments.extend(chunk[offset:end])
            line = bytes(self.fragments)
            self.fragments.clear()
            self.row_index += 1
            try:
                row = parse_json(line.decode('utf-8', 'replace'))
            except Exception as error:
                if self.issue is None:
                    self.issue = ValueError('corrupt session log: row %s is not valid JSON' % self.row_index)
                    self.issue.cause = error
            else:
                if self.issue is not None:
                    if isinstance(row, dict) and row.get('type') == 'turn/end':
                        raise self.issue
                else:
                    self.restore.decodeRow(row)
            offset = end+1


def assertIndependentHeaderFrame(plaintext):
    if not plaintext or plaintext.find(b'\n') != len(plaintext)-1:
        raise ValueError('corrupt Zstandard session log: first frame is not exactly one header line')


def assertCurrentAssistantStreams(events):
    for index, event in enumerate(events):
        if event['type'] not in ('assistant/message', 'assistant/attempt'):
            continue
        data, assembler = event['data'], BlockAssembler()
        try:
            timed = expandAssistantStream(data['stream'])
            for value in timed:
                assembler.push(value['chunk'])
        except Exception as error:
            failure = ValueError('seed %s at index %s has an invalid embedded stream' % (event['type'], index))
            failure.cause = error
            raise failure from error
        if event['type'] == 'assistant/attempt' or not timed:
            continue
        content = assembler.interruptedBlocks() if data.get('interrupted') is True else assembler.blocks()
        checks = [('content', data['message']['content'], content),
            ('usage', data.get('usage', UNDEFINED), assembler.usage),
            ('replay state', data['message']['source'].get('replayState', UNDEFINED), assembler.replayState)]
        for label, actual, expected in checks:
            if not equal_json(actual, expected):
                raise ValueError('seed assistant/message at index %s %s disagrees with its embedded stream' % (index, label))


class JsonlGenerationRuntime:
    def __init__(self, overrides=None):
        options = overrides or {}
        self.fs = options.get('fs', NativeGenerationFileSystem())
        self.randomToken = options.get('randomToken', lambda:secrets.token_hex(12))
        self.barrier = options.get('barrier', lambda phase,attempt:None)
        self.publishNew = options.get('publishNew', publish_new_file)

    async def io(self, method, *args):
        # Native blocking I/O leaves the event loop. Injected async seams remain awaitable.
        function = getattr(self.fs, method)
        if type(self.fs) is NativeGenerationFileSystem:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda:function(*args))
        return await resolved(function(*args))

    async def fileio(self, function, *args):
        if type(self.fs) is NativeGenerationFileSystem:
            return await asyncio.get_running_loop().run_in_executor(None, lambda:function(*args))
        return await resolved(function(*args))

    async def readStable(self, path, signal=None):
        throw_aborted(signal)
        before = await self.io('stat', path)
        for attempt in range(2):
            data = await self.io('readFile', path, signal)
            throw_aborted(signal)
            after = await self.io('stat', path)
            if identity(before) == identity(after):
                throw_aborted(signal)
                return dict(bytes=data, identity=after)
            if attempt == 1:
                return dict(bytes=data[:before['size']], identity=before)
            before = after

    async def decodeMigration(self, data, compression, source_version, format_adapter, validate_header=None, signal=None):
        throw_aborted(signal)
        async def start(header):
            try:
                value = parse_json(header[:-1].decode('utf-8', 'replace'))
            except Exception as error:
                failure = ValueError('corrupt session log: header line is not valid JSON')
                failure.cause = error
                raise failure from error
            if not isinstance(value, dict):
                raise ValueError('corrupt session log: first line is not a JSON object')
            version = value.get('version', UNDEFINED)
            from dsh.core.session.current import safe
            if not safe(version, True, True):
                raise ValueError('corrupt session log: header version is not a non-negative safe integer')
            if type(source_version) not in (int, float) or version != source_version:
                raise ValueError('resolved JSONL source filename identifies v%s, but its header identifies v%s' % (display(source_version), display(version)))
            if validate_header is not None:
                await resolved(validate_header(value))
            return MigratingJsonlRows(call(format_adapter, 'createRestore', value))

        async def consume(rows, chunk):
            deadline = time.monotonic()+0.5
            for offset in range(0,len(chunk),1024*1024):
                rows.write(chunk[offset:offset+1024*1024])
                if time.monotonic() >= deadline:
                    await asyncio.sleep(0)
                    throw_aborted(signal)
                    deadline = time.monotonic()+0.5
        if compression == 'none':
            end = data.find(b'\n')
            if end < 0:
                raise ValueError('empty or header-less session log')
            rows = await start(data[:end+1])
            throw_aborted(signal)
            last = data.rfind(b'\n')
            if last > end:
                await consume(rows, data[end+1:last+1])
        else:
            scanned = scan_frames(data)
            if not scanned['frames']:
                raise ValueError('empty or header-less Zstandard session log')
            first = scanned['frames'][0]
            header = decompress_frame(data[first['start']:first['end']])
            assertIndependentHeaderFrame(header)
            rows = await start(header)
            throw_aborted(signal)
            for frame in scanned['frames'][1:]:
                await consume(rows, decompress_frame(data[frame['start']:frame['end']]))
            if rows.fragments:
                raise ValueError('corrupt Zstandard session log: complete frame contains a torn JSONL record')
            if 'tornStart' in scanned:
                try:
                    recovered = decompress_frame(data[scanned['tornStart']:], incomplete=True)
                except Exception:
                    throw_aborted(signal)
                    recovered = b''
                throw_aborted(signal)
                end = recovered.rfind(b'\n')
                if end >= 0:
                    await consume(rows, recovered[:end+1])
        return rows.restore.finish()

    async def verify(self, path, compression, expectedId, expectedEventCount, expectedPrefix=None):
        before = await self.io('stat', path)
        data = await self.io('readFile', path)
        after = await self.io('stat', path)
        if expectedPrefix is not None:
            if len(data) < expectedPrefix['bytes']:
                raise ValueError('target bytes are shorter than the migrated generation')
            digest = hashlib.sha256(data[:expectedPrefix['bytes']]).hexdigest()
            if digest != expectedPrefix['digest']:
                raise ValueError('target bytes do not begin with the migrated generation')
            return dict(identity=after, bytes=expectedPrefix['bytes'], digest=digest)
        if identity(before) != identity(after):
            raise ValueError('current session generation changed during verification')
        if compression == 'none':
            end = data.find(b'\n')
            if end < 0:
                raise ValueError('empty or header-less session log')
            scanner = SessionLogScanner(data[:end+1], 'strict')
            scanner.write(data[end+1:])
        else:
            scanned = scan_frames(data)
            if not scanned['frames']:
                raise ValueError('empty or header-less Zstandard session log')
            if 'tornStart' in scanned:
                raise ValueError('current session generation has a torn physical tail')
            first = scanned['frames'][0]
            header = decompress_frame(data[first['start']:first['end']])
            assertIndependentHeaderFrame(header)
            scanner = SessionLogScanner(header, 'strict')
            for frame in scanned['frames'][1:]:
                scanner.write(decompress_frame(data[frame['start']:frame['end']]))
        decoded = scanner.finish()
        if decoded['committedBytes'] != scanner.checkpoint()['inputBytes']:
            raise ValueError('current session generation has a torn physical tail')
        # Stored vocabulary/relationships and installed Session admission are separate boundaries.
        from dsh.session.storage_contract import validateStoredEvents
        artifact = dict(header=decoded['meta'], inheritedEventCount=decoded['inheritedEventCount'], events=decoded['events'])
        validateStoredEvents(decoded['meta'], decoded['events'], dict(kind='jsonl', path=path))
        if decoded['meta']['id'] != expectedId:
            raise ValueError('current session generation contains id "%s", expected "%s"' % (decoded['meta']['id'], expectedId))
        if len(decoded['events']) != expectedEventCount:
            raise ValueError('current session generation contains %s events, expected %s' % (len(decoded['events']), expectedEventCount))
        validateInstalledCurrentSessionArtifact(artifact)
        assertCurrentAssistantStreams(decoded['events'])
        return dict(identity=after, bytes=len(data), digest=hashlib.sha256(data).hexdigest())

    async def prepare(self, options):
        source, current = str(options['sourcePath']), str(options['currentPath'])
        version, compression = options['sourceVersion'], options['compression']
        adapter = options.get('format', default_format_adapter)
        target_version = member(adapter, 'currentVersion')
        source_name, target_name = generationLogFilename(version, compression), generationLogFilename(target_version, compression)
        if os.path.basename(source) != source_name:
            raise ValueError('resolved JSONL source path must end with "%s": %s' % (source_name, source))
        if os.path.basename(current) != target_name:
            raise ValueError('current JSONL generation path must end with "%s": %s' % (target_name, current))
        if os.path.dirname(source) != os.path.dirname(current):
            raise ValueError('source and current JSONL generations must share one Session directory')
        if version >= target_version:
            raise ValueError('migration preparation requires a historical source, got v%s' % version)
        snapshot = await self.readStable(source, options.get('signal'))
        try:
            artifact = await self.decodeMigration(snapshot['bytes'], compression, version, adapter, options.get('validateHistoricalHeader'), options.get('signal'))
        except Exception as error:
            classifier = member(adapter, 'isUnsupportedMigrationError')
            if classifier is not UNDEFINED and classifier(error) is True:
                raise JsonlGenerationUnsupportedMigrationError(version, error) from error
            raise
        if artifact['header']['version'] != target_version:
            raise ValueError('format migration returned v%s, expected v%s' % (artifact['header']['version'], target_version))
        return PreparedJsonlMigration(self, options, adapter, artifact, snapshot['identity'])


default_format_adapter = dict(currentVersion=3,
    createRestore=lambda header:sessionFormatCatalog.createRestore(header, dict(recovery='recoverable', validation='transformed')),
    encodeHeader=sessionFormatCatalog.encodeCurrentHeader, encodeEvent=sessionFormatCatalog.encodeCurrentEvent,
    isUnsupportedMigrationError=lambda error:isinstance(error, SessionFormatUnsupportedMigrationError))


class PreparedJsonlMigration:
    def __init__(self, runtime, options, adapter, artifact, source_identity):
        self.runtime, self.options, self.adapter = runtime, options, adapter
        self.artifact, self.sourceIdentity, self.publication = artifact, source_identity, None

    async def publish(self):
        if self.publication is None:
            self.publication = asyncio.create_task(self._publish())
        return await asyncio.shield(self.publication)

    async def _remove(self, path, primary=None):
        try:
            await self.runtime.io('rm', path)
        except Exception as cleanup:
            if primary is not None:
                raise GenerationAggregateError([primary,cleanup], 'failed to clean migration temporary "%s" after an earlier failure' % path) from primary

    async def _write_stage(self):
        runtime, current = self.runtime, str(self.options['currentPath'])
        compression = self.options['compression']
        while True:
            path = os.path.join(os.path.dirname(current), 'session.migration.%s%s.tmp' % (runtime.randomToken(), logSuffix(compression)))
            try:
                file = await runtime.io('open', path, 'wx', 0o600)
                break
            except FileExistsError:
                continue
        failure, digest, total = None, hashlib.sha256(), 0
        try:
            async def write(data):
                nonlocal total
                await runtime.fileio(file.write, data)
                digest.update(data)
                total += len(data)
            header = (stringifyJson(call(self.adapter, 'encodeHeader', self.artifact['header'], self.artifact['inheritedEventCount']), 'migrated session header')+'\n').encode('utf-8')
            await write(compress_frame(header) if compression == 'zstd' else header)
            from dsh.session.jsonl_zstd import compress_chunks
            async def rows():
                parts, size, work = [], 0, 0
                for index, event in enumerate(self.artifact['events']):
                    line = (stringifyJson(call(self.adapter, 'encodeEvent', event), 'migrated Session event %s' % index)+'\n').encode('utf-8')
                    parts.append(line)
                    size += len(line)
                    work += len(line)
                    if size >= 1024*1024:
                        yield b''.join(parts)
                        parts, size = [], 0
                    if work >= 1024*1024:
                        await asyncio.sleep(0)
                        work = 0
                if parts:
                    yield b''.join(parts)
            if compression == 'zstd' and self.artifact['events']:
                async for chunk in compress_chunks(rows()):
                    await write(chunk)
            elif compression == 'none':
                async for chunk in rows():
                    await write(chunk)
            await runtime.fileio(file.flush)
            await runtime.fileio(os.fsync, file.fileno())
        except BaseException as error:
            failure = error
        try:
            await runtime.fileio(file.close)
        except BaseException as error:
            failure = error if failure is None else GenerationAggregateError([failure,error], 'failed to write and close migration stage "%s"' % path)
        if failure is not None:
            await self._remove(path, failure)
            raise failure
        return dict(path=path, bytes=total, digest=digest.hexdigest())

    async def _publish(self):
        await asyncio.sleep(0)
        runtime, options = self.runtime, self.options
        source, current, compression = str(options['sourcePath']), str(options['currentPath']), options['compression']
        from dsh.session.generation_verifier import verifyCurrentGenerationInWorker
        verify = options.get('verifyCurrentFile', verifyCurrentGenerationInWorker)
        staged = await self._write_stage()
        try:
            verified = await resolved(verify(staged['path'], compression, self.artifact['header']['id'], len(self.artifact['events'])))
            if verified['bytes'] != staged['bytes'] or verified['digest'] != staged['digest']:
                raise ValueError('staged session generation changed during verification')
            await resolved(runtime.barrier('before-source-check',1))
            before = await runtime.io('stat', source)
            if identity(before) != identity(self.sourceIdentity):
                raise JsonlGenerationSourceChangedError(source)
            try:
                await resolved(runtime.publishNew(staged['path'], current))
                published = True
            except FileExistsError:
                published = False
            if published and os.name == 'nt':
                staged['path'] = ''
            await resolved(runtime.barrier('after-publication',1))
            if published:
                if staged['path']:
                    await self._remove(staged['path'])
                    staged['path'] = ''
                return await runtime.io('stat', current)
            try:
                names = await runtime.io('readdir', os.path.dirname(current))
                if os.path.basename(current) not in names:
                    other = next((name for name in names if name.lower() == os.path.basename(current).lower()), None)
                    if other is not None:
                        raise ValueError('target resolves to noncanonical directory entry "%s"' % other)
                metadata = await runtime.io('lstat', current)
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    raise ValueError('target is a ' + ('symbolic link' if stat.S_ISLNK(metadata.st_mode) else 'non-regular file'))
                winner = await resolved(verify(current, compression, self.artifact['header']['id'], len(self.artifact['events']), staged))
                if winner['bytes'] != staged['bytes'] or winner['digest'] != staged['digest']:
                    raise ValueError('target bytes differ from the migrated generation')
            except OSError:
                raise
            except Exception as error:
                raise JsonlGenerationTargetConflictError(current, error) from error
            await self._remove(staged['path'])
            staged['path'] = ''
            return winner['identity']
        except Exception as error:
            if staged['path']:
                await self._remove(staged['path'], error)
            raise


_default_runtime = JsonlGenerationRuntime()
prepareJsonlMigration = _default_runtime.prepare
readStableJsonlFile = _default_runtime.readStable
verifyJsonlCurrentGeneration = _default_runtime.verify
createJsonlGenerationRuntime = JsonlGenerationRuntime


async def readDecodedJsonlSource(path, version, compression, format, signal=None):
    """Read one immutable source through an explicit, publication-free codec."""
    source = await readStableJsonlFile(path, signal)
    try:
        artifact = await _default_runtime.decodeMigration(source['bytes'], compression, version, format, None, signal)
    except Exception as error:
        if getattr(signal, 'aborted', False) or isinstance(error, SessionFormatError):
            raise
        name = getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error')
        failure = SessionFormatError('%s: %s' % (name, error))
        failure.cause = error
        raise failure from error
    return dict(artifact=artifact, identity=source['identity'])
