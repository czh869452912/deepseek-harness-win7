"""Current-generation JSONL backend and explicit v3 handle service.

Historical reads prepare an immutable successor in memory. Only a write open
publishes it, while holding the native cross-process lease. The active profile
is switched separately together with Session and its handle-owning consumers.
"""
import asyncio
import hashlib
import os
import tempfile
import time
from collections import OrderedDict

from dsh.core.abort import AbortController, AbortError
from dsh.core.session.json import UNDEFINED, deep_freeze
from dsh.core.session.types import SessionId, SessionLogOffset
from dsh.cordis.json_text import stringify_json
from dsh.session.durable_publish import ensure_durable_directory, publish_new_file, discard_staging
from dsh.session.file_io import filesystem_path, open_shared_read
from dsh.session.file_revision import file_revision
from dsh.session.generation import (
    readStableJsonlFile, default_format_adapter, JsonlGenerationRuntime,
    JsonlGenerationSourceChangedError, JsonlGenerationUnsupportedMigrationError)
from dsh.session.format_catalog import sessionFormatCatalog
from dsh.session.format_v2_to_v3.payload import display
from dsh.session.jsonl_current import (
    generationLogFilename, parseGenerationLogFilename, generationLogPath, logPath,
    sessionDir, header_bytes, eventLines, SessionLogScanner, scanLog, assertNoRetiredHeaderFields)
from dsh.session.jsonl_handle import JsonlSessionHandle, JsonlBackendTracker, StorageAggregateError, signal_of, failed
from dsh.session.jsonl_store import JsonlStore
from dsh.session.jsonl_zstd import compress_frame, decompress_frame, scan_frames
from dsh.session.lease import SessionWriteLease
from dsh.session.persistence import (
    SessionAlreadyExistsError, SessionFormatUnsupportedError,
    SessionPersistenceCorruptionError, SessionPersistenceNotFoundError)
from dsh.session.preparations import throw_aborted
from dsh.session.sqlite_json import parse_json
from dsh.session.storage_contract import (
    field, materializeCreateHeader, validateStoredEvents, assertStoredId,
    sessionFormatVersionRefusal, unsupported)


def revision(identity):
    return ':'.join(str(identity[key]) for key in ('dev','ino','size','mtimeNs','ctimeNs'))


def error_string(error):
    return '%s: %s' % (getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error'), error)


class CurrentJsonlSessionPersistence(JsonlStore):
    """Handle-based service; shared base supplies only durable file primitives."""
    name = 'session-persistence-jsonl'

    def __init__(self, root, compression='zstd', ctx=None, format_version=3):
        super().__init__(root, compression, pack_chunks=False)
        self.ctx = ctx
        self.format_version, self.catalog = format_version, sessionFormatCatalog
        if format_version == 4:
            from dsh.session.format_catalog import candidateSessionFormatCatalog
            self.catalog = candidateSessionFormatCatalog
        self.generation_runtime = JsonlGenerationRuntime(dict(formatVersion=format_version))
        self.tracker = JsonlBackendTracker(self.name)
        self.coldLogMemo = OrderedDict()
        self.migrationPreparations = {}
        self._encoding_task = None
        if ctx is not None:
            self.tracker.install(ctx)

    def locate(self, meta, opposite=False):
        return logPath(self.root, field(meta,'cwd'), field(meta,'id'),
                       ('none' if self.compression=='zstd' else 'zstd') if opposite else self.compression, self.format_version)

    def _opposite_generation(self, directory):
        try:
            names = os.listdir(filesystem_path(directory))
        except FileNotFoundError:
            return None
        opposite = 'none' if self.compression=='zstd' else 'zstd'
        candidates = [(parseGenerationLogFilename(name, opposite), name) for name in names]
        candidates = [item for item in candidates if item[0] is not None]
        if not candidates:
            return None
        return os.path.join(directory,max(candidates,key=lambda item:item[0])[1])

    def _ensure_encoding(self):
        if self.root_checked:
            if self.root_error is not None:
                raise self.root_error
            return
        self.root_checked = True
        try:
            for project in self._projects():
                for directory in self._sessions(project):
                    path = self._opposite_generation(directory)
                    if path is not None:
                        raise self._encoding_error(path)
        except BaseException as error:
            self.root_error = error
            raise

    async def ensureRootEncoding(self):
        if self._encoding_task is None:
            self._encoding_task = asyncio.create_task(self._run(self._ensure_encoding))
        await asyncio.shield(self._encoding_task)

    def _resolve_generation(self, directory):
        try:
            names = os.listdir(filesystem_path(directory))
        except FileNotFoundError:
            return None
        generations = []
        opposite = 'none' if self.compression=='zstd' else 'zstd'
        for name in names:
            version = parseGenerationLogFilename(name,self.compression)
            if version is not None:
                generations.append((version,name))
            elif parseGenerationLogFilename(name,opposite) is not None:
                raise self._encoding_error(os.path.join(directory,name))
        if not generations:
            return None
        version,name = max(generations,key=lambda item:item[0])
        return dict(sourcePath=os.path.join(directory,name), sourceVersion=version,
                    currentPath=os.path.join(directory,generationLogFilename(self.format_version,self.compression)))

    def _find(self, session_id):
        from dsh.session.jsonl_format import encode_segment
        matches = []
        for project in self._projects():
            encoded = encode_segment(session_id)
            for suffix in ('.jsonl.zstd','.jsonl'):
                path = os.path.join(project,encoded+suffix)
                if self._exists(path):
                    raise self._legacy_error(path)
            selected = self._resolve_generation(os.path.join(project,encoded))
            if selected is not None:
                matches.append(selected)
        if len(matches)>1:
            raise ValueError('duplicate JSONL session id "%s" appears in multiple project directories' % session_id)
        return matches[0] if matches else None

    async def findLog(self, session_id, signal=None):
        throw_aborted(signal)
        selected = await self._run(self._find,session_id)
        throw_aborted(signal)
        return selected

    def create(self, header, options=None):
        # JS async functions reach their first await on invocation. Snapshot now,
        # so callers cannot mutate metadata while root/collision probes run.
        try:
            throw_aborted(signal_of(options))
            snapshot = materializeCreateHeader(header)
            from dsh.session.jsonl_current import toHeaderLine
            cut = field(options,'inheritedEventCount')
            toHeaderLine(snapshot,cut,self.format_version)
            cut = SessionLogOffset(0 if cut is UNDEFINED or cut is None else cut)
        except Exception as error:
            return failed(error)
        return asyncio.create_task(self._create_handle(snapshot,cut,signal_of(options)))

    async def _create_handle(self, header, cut, signal):
        await self.ensureRootEncoding()
        throw_aborted(signal)
        if self.tracker.hasPending(header['id']) or await self.findLog(header['id'],signal) is not None:
            raise SessionAlreadyExistsError(header['id'])
        throw_aborted(signal)
        self.tracker.registerCreated(header,cut)
        return self.tracker.adopt(JsonlSessionHandle(self,header['id'],header,'write',dict(cursor=0,materialized=False,inheritedEventCount=cut)))

    async def open(self, session_id, access, options=None):
        pending = asyncio.create_task(self._open(session_id,access,options))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            # A Python observer may cancel its await, unlike a JS Promise.
            # Keep a publication leased until it settles, then release any
            # unclaimed returned handle before propagating the cancellation.
            try:
                handle = await pending
                await handle.close()
            except Exception:
                pass
            raise

    async def _open(self, session_id, access, options=None):
        signal = signal_of(options)
        throw_aborted(signal)
        await self.ensureRootEncoding()
        throw_aborted(signal)
        pending = self.tracker.pendingOf(session_id)
        if access=='read':
            if pending is not None:
                return self.tracker.adopt(JsonlSessionHandle(self,session_id,pending['header'],'read',dict(cursor=0,materialized=False,inheritedEventCount=pending['inheritedEventCount'])))
            stored = await self.requireStoredLog(session_id,signal)
            state = dict(cursor=0,materialized=True,inheritedEventCount=stored['inheritedEventCount'])
            if stored['status']=='prepared':
                state['primed'] = stored
            return self.tracker.adopt(JsonlSessionHandle(self,session_id,stored['meta'],'read',state))
        self.tracker.claimWrite(session_id)
        lease = None
        try:
            selected = await self.findLog(session_id,signal)
            if selected is None:
                raise SessionPersistenceNotFoundError(session_id)
            lease = await SessionWriteLease.acquire(os.path.dirname(selected['currentPath']),session_id)
            stored = await self.requireStoredLog(session_id,signal)
            throw_aborted(signal)
            if stored['status']=='prepared':
                stored = await self.publishStoredMigration(session_id,stored)
            throw_aborted(signal)
            state = dict(cursor=len(stored['events']),materialized=True,inheritedEventCount=stored['inheritedEventCount'],
                         recoveredTail=stored['recoveredTail'],primed=stored)
            if stored.get('tornTruncateTo') is not None:
                state['tornTruncateTo'] = stored['tornTruncateTo']
            return self.tracker.adopt(JsonlSessionHandle(self,session_id,stored['meta'],'write',state,lease))
        except BaseException as error:
            try:
                if lease is not None:
                    await lease.release()
            except Exception as release_error:
                raise StorageAggregateError([error,release_error],'session "%s": write open failed and its lock release failed' % session_id) from error
            finally:
                self.tracker.releaseClaim(session_id)
            raise

    async def flush(self):
        await self.tracker.flushAll()

    async def close(self):
        await self.tracker.dispose()

    async def stat(self, session_id, options=None):
        signal = signal_of(options)
        throw_aborted(signal)
        await self.ensureRootEncoding()
        throw_aborted(signal)
        pending = self.tracker.pendingOf(session_id)
        if pending is not None:
            return dict(header=pending['header'],revision=pending['revision'])
        selected = await self.findLog(session_id,signal)
        if selected is None:
            return None
        header = await self.readGenerationHeader(selected,session_id,signal)
        if header is None:
            return None
        try:
            identity = await self._physical_identity(selected['sourcePath'])
            throw_aborted(signal)
            token = revision(identity)
            result = dict(header=header,revision=token,sizeBytes=identity['size'])
            if self.format_version == 4:
                if selected['sourceVersion'] < self.format_version:
                    result['revision'] = token+':'+await self.historicalCorpusRevision(signal)
                result.update(formatStatus='migration-required' if selected['sourceVersion'] < self.format_version else 'current',
                              location=dict(kind='jsonl',path=selected['sourcePath']))
            return result
        except FileNotFoundError:
            throw_aborted(signal)
            return None

    async def list(self, options=None):
        if self.format_version == 4:
            return await self._list_v4(options)
        signal = signal_of(options)
        throw_aborted(signal)
        pending = list(self.tracker.pendingEntries())
        await self.ensureRootEncoding()
        snapshots, ids = [],set()
        for project in await self._run(self._projects):
            for directory in await self._run(self._sessions,project):
                throw_aborted(signal)
                selected = await self._run(self._resolve_generation,directory)
                if selected is None:
                    continue
                try:
                    header = await self.readGenerationHeader(selected,None,signal)
                except SessionFormatUnsupportedError:
                    continue
                if header is None:
                    continue
                session_id = header['id']
                if session_id in ids:
                    raise ValueError('duplicate JSONL session id "%s" appears in multiple project directories' % session_id)
                try:
                    identity = await self._physical_identity(selected['sourcePath'])
                except FileNotFoundError:
                    continue
                ids.add(session_id)
                snapshots.append(dict(header=header,revision=revision(identity),sizeBytes=identity['size']))
        for session_id,entry in pending:
            if session_id not in ids:
                snapshots.append(dict(header=entry['header'],revision=entry['revision']))
        throw_aborted(signal)
        return snapshots

    async def _list_v4(self, options):
        signal = signal_of(options)
        pending = list(self.tracker.pendingEntries())
        artifacts = await self.listArtifacts(signal)
        corpus = await self.historicalCorpusRevision(signal) if any(item['sourceVersion'] < self.format_version for item in artifacts) else None
        snapshots, ids = [], set()
        for artifact in artifacts:
            throw_aborted(signal)
            try:
                identity = await self._physical_identity(artifact['path'])
            except FileNotFoundError:
                continue
            ids.add(artifact['header']['id'])
            token = revision(identity)
            snapshots.append(dict(header=artifact['header'],formatStatus=artifact['formatStatus'],
                revision=token+':'+corpus if artifact['sourceVersion'] < self.format_version else token,
                sizeBytes=identity['size'],location=dict(kind='jsonl',path=artifact['path'])))
        snapshots.extend(dict(header=entry['header'],revision=entry['revision']) for sid,entry in pending if sid not in ids)
        throw_aborted(signal)
        return snapshots

    async def _physical_identity(self, path):
        from dsh.session.file_revision import filesystem_identity
        return await self._run(filesystem_identity,path)

    def _current_header(self, header):
        if header['version']!=self.format_version:
            raise ValueError('format catalog returned non-current logical header v%s' % display(header['version']))
        result = dict(version=self.format_version,id=SessionId(header['id']),createdAt=header['createdAt'],
                      isSeeded=header['isSeeded'],delegationDepth=header['delegationDepth'])
        for key in ('cwd','parentSession','origin','agentPreset'):
            if key in header:
                result[key] = SessionId(header[key]) if key=='parentSession' else header[key]
        return result

    def _assert_identity(self, path, version, meta, expected_id=None):
        if expected_id is not None and meta['id']!=expected_id:
            raise ValueError('corrupt session log "%s": requested id "%s" does not match header id "%s"' % (path,expected_id,meta['id']))
        try:
            expected = generationLogPath(self.root,field(meta,'cwd'),meta['id'],version,self.compression)
        except Exception as error:
            raise ValueError('corrupt session log "%s": header id cannot name a storage path' % path) from error
        if path!=expected:
            # Resolve path spelling aliases, not hard links (Source uses realpath).
            try:
                os.stat(filesystem_path(expected))
                matches = os.path.normcase(os.path.realpath(path))==os.path.normcase(os.path.realpath(expected))
            except FileNotFoundError:
                matches = False
            if not matches:
                raise ValueError('corrupt session log "%s": header id "%s" and cwd identify "%s"' % (path,meta['id'],expected))

    async def readGenerationHeader(self, selected, expected_id=None, signal=None):
        throw_aborted(signal)
        try:
            first = await self._run(self._first_line,selected['sourcePath'],signal)
        except FileNotFoundError:
            throw_aborted(signal)
            return None
        throw_aborted(signal)
        if first is None:
            return None
        try:
            value = parse_json(first)
        except Exception:
            return None
        assertNoRetiredHeaderFields(value)
        result = self.catalog.readHeader(value)
        if 'storedVersion' in result and result['storedVersion']!=selected['sourceVersion']:
            raise ValueError('session generation filename identifies v%s, but its header identifies v%s' % (display(selected['sourceVersion']),display(result['storedVersion'])))
        if result['status']=='unsupported':
            reason = sessionFormatVersionRefusal(field(value,'id'),result['storedVersion'],self.format_version) if result['storedVersion']>self.format_version else result['reason']
            raise unsupported(reason,dict(kind='jsonl',path=selected['sourcePath']))
        if result['status']=='malformed':
            return None
        header = self._current_header(result['header'])
        await self._run(self._assert_identity,selected['sourcePath'],selected['sourceVersion'],header,expected_id)
        throw_aborted(signal)
        return header

    def _first_line(self, path, signal=None):
        throw_aborted(signal)
        with open_shared_read(path) as stream:
            content = bytearray()
            while True:
                throw_aborted(signal)
                chunk = stream.read(8192)
                throw_aborted(signal)
                if not chunk:
                    return None
                if self.compression=='none':
                    boundary = chunk.find(b'\n')
                    content.extend(chunk if boundary<0 else chunk[:boundary])
                    if boundary>=0:
                        return bytes(content).decode('utf-8','replace')
                    continue
                content.extend(chunk)
                frames = scan_frames(content,1)['frames']
                if not frames:
                    continue
                frame = frames[0]
                try:
                    decoded = decompress_frame(bytes(content[frame['start']:frame['end']]))
                except Exception as error:
                    throw_aborted(signal)
                    failure = ValueError('corrupt Zstandard session log: header frame failed validation')
                    failure.cause = error
                    raise failure from error
                self._header_frame(decoded)
                return decoded[:-1].decode('utf-8','replace')

    def _memoize(self, session_id, stored):
        self.coldLogMemo.pop(session_id,None)
        self.coldLogMemo[session_id] = stored
        while len(self.coldLogMemo)>2:
            self.coldLogMemo.popitem(last=False)
        return stored

    def _memo(self, session_id, token, status):
        value = self.coldLogMemo.get(session_id)
        if value is not None and value['revision']==token and value['status']==status:
            self.coldLogMemo.move_to_end(session_id)
            return value

    async def requireStoredLog(self, session_id, signal=None):
        selected = await self.findLog(session_id,signal)
        if selected is None:
            raise SessionPersistenceNotFoundError(session_id)
        if selected['sourceVersion']<self.format_version:
            token = await self._run(file_revision,selected['sourcePath'])
            throw_aborted(signal)
            entry = self.migrationPreparations.get(session_id)
            if entry is None or entry['path']!=selected['sourcePath'] or entry['revision']!=token:
                controller = AbortController()
                entry = dict(path=selected['sourcePath'],revision=token,controller=controller,waiters=0,settled=False)
                async def prepare(owned=entry):
                    try:
                        memo = self._memo(session_id,token,'prepared')
                        if memo is not None:
                            validate = memo.get('validateRelatedSources')
                            if validate is not None:
                                try:
                                    await validate()
                                except Exception as error:
                                    self.coldLogMemo.pop(session_id,None)
                                    raise self._generation_failure(session_id,selected,error)
                            return memo
                        return await self._prepare_migration(session_id,selected,controller.signal)
                    finally:
                        owned['settled'] = True
                        if self.migrationPreparations.get(session_id) is owned:
                            self.migrationPreparations.pop(session_id,None)
                entry['task'] = asyncio.create_task(prepare())
                # A last observer may leave before work sees its owned abort.
                entry['task'].add_done_callback(lambda task:task.exception() if not task.cancelled() else None)
                self.migrationPreparations[session_id] = entry
            throw_aborted(signal)
            return await self._wait_preparation(session_id,entry,signal)
        if selected['sourceVersion']>self.format_version:
            header = await self.readGenerationHeader(selected,session_id,signal)
            if header is None:
                raise SessionPersistenceCorruptionError('session "%s": stored log has a malformed header (raw log: %s)' % (session_id,selected['sourcePath']),dict(cause=ValueError('malformed Session header')))
            raise unsupported(sessionFormatVersionRefusal(session_id,selected['sourceVersion'],self.format_version),dict(kind='jsonl',path=selected['sourcePath']))
        return await self.readStoredLog(selected['sourcePath'],session_id,signal)

    async def _wait_preparation(self, session_id, entry, signal):
        entry['waiters'] += 1
        remove = None
        abort = None
        try:
            if signal is None:
                return await asyncio.shield(entry['task'])
            throw_aborted(signal)
            abort = asyncio.get_running_loop().create_future()
            def stop(*args):
                if not abort.done():
                    error = signal.reason
                    if not isinstance(error,BaseException):
                        error = ValueError('session migration preparation aborted')
                        error.cause = signal.reason
                    abort.set_exception(error)
            remove = signal.add_listener('abort',stop)
            done,_ = await asyncio.wait([entry['task'],abort],return_when=asyncio.FIRST_COMPLETED)
            if abort in done:
                return abort.result()
            return entry['task'].result()
        finally:
            if remove is not None:
                remove()
            if abort is not None:
                if not abort.done():abort.cancel()
                elif not abort.cancelled():abort.exception()
            entry['waiters'] -= 1
            if not entry['waiters'] and not entry['settled']:
                if self.migrationPreparations.get(session_id) is entry:
                    self.migrationPreparations.pop(session_id,None)
                entry['controller'].abort()

    def _generation_failure(self, session_id, selected, error):
        path = selected['sourcePath']
        if isinstance(error,JsonlGenerationUnsupportedMigrationError):
            return unsupported('%s; source v%s artifact remains unchanged' % (error,error.fromVersion),dict(kind='jsonl',path=path))
        if isinstance(error,(JsonlGenerationSourceChangedError,SessionFormatUnsupportedError,SessionPersistenceCorruptionError,OSError,AbortError)):
            return error
        return SessionPersistenceCorruptionError('session "%s": stored log is corrupt: %s (raw log: %s)' % (session_id,error_string(error),path),dict(cause=error))

    async def _prepare_migration(self, session_id, selected, signal):
        async def validate(value):
            result = self.catalog.readHeader(value)
            if result['status'] in ('current','migration-required'):
                await self._run(self._assert_identity,selected['sourcePath'],selected['sourceVersion'],self._current_header(result['header']),session_id)
                throw_aborted(signal)
        try:
            adapter = default_format_adapter
            validate_related = None
            if self.format_version == 4:
                from dsh.session.catalog_migration import prepareCatalogFacts
                from dsh.session.format_catalog import createSessionFormatCatalogWithChildren
                from dsh.session.format import SessionFormatUnsupportedMigrationError
                async def children():
                    return [item for item in await self.listArtifacts(signal)
                            if item['header'].get('origin') == 'subagent' and item['header'].get('parentSession') == session_id]
                sources = await children()
                related = await prepareCatalogFacts(session_id,sources,self.compression,signal,self.catalog)
                for failure in related.failures:
                    if self.ctx is not None:
                        self.ctx.logger.warn('%s: session "%s" catalog retained a child with unknown descriptor (raw log: %s): %s' %
                            (self.name,session_id,failure['path'],error_string(failure['error'])))
                membership = sorted(item['path'] for item in sources)
                async def validate_related():
                    current = sorted(item['path'] for item in await children())
                    before, after = set(membership), set(current)
                    changed = next((path for path in current if path not in before), None)
                    if changed is None:
                        changed = next((path for path in membership if path not in after), None)
                    if changed is not None:
                        raise JsonlGenerationSourceChangedError(changed)
                    await related.validate()
                catalog = createSessionFormatCatalogWithChildren(related.facts)
                adapter = dict(currentVersion=4,createRestore=lambda header:catalog.createRestore(header,dict(recovery='recoverable',validation='transformed')),
                    encodeHeader=catalog.encodeCurrentHeader,encodeEvent=catalog.encodeCurrentEvent,
                    isUnsupportedMigrationError=lambda error:isinstance(error,SessionFormatUnsupportedMigrationError))
            options = dict(selected,compression=self.compression,format=adapter,validateHistoricalHeader=validate,signal=signal)
            if validate_related is not None:
                options['validateRelatedSources'] = validate_related
            prepared = await self.generation_runtime.prepare(options)
        except Exception as error:
            raise self._generation_failure(session_id,selected,error)
        artifact = prepared.artifact
        meta = self._current_header(artifact['header'])
        assertStoredId(session_id,meta)
        validateStoredEvents(meta,artifact['events'],dict(kind='jsonl',path=selected['sourcePath']),self.format_version)
        stored = dict(status='prepared',meta=meta,eventState='shared-frozen',events=deep_freeze(artifact['events']),
                      recoveredTail=[],inheritedEventCount=SessionLogOffset(artifact['inheritedEventCount']),
                      revision=revision(prepared.sourceIdentity),publication=dict(source=selected,value=prepared))
        if validate_related is not None:
            stored['validateRelatedSources'] = validate_related
        return self._memoize(session_id,stored)

    async def listArtifacts(self, signal=None):
        """Read selected physical memberships without preparing any child body."""
        throw_aborted(signal)
        await self.ensureRootEncoding()
        artifacts, ids = [], set()
        for selected in await self.listGenerations(signal):
            throw_aborted(signal)
            try:
                header = await self.readGenerationHeader(selected,None,signal)
            except (SessionFormatUnsupportedError,SessionPersistenceCorruptionError):
                continue
            if header is None:
                continue
            if header['id'] in ids:
                raise ValueError('duplicate JSONL session id "%s" appears in multiple project directories' % header['id'])
            ids.add(header['id'])
            artifacts.append(dict(header=header,path=selected['sourcePath'],sourceVersion=selected['sourceVersion'],
                formatStatus='migration-required' if selected['sourceVersion'] < self.format_version else 'current'))
        throw_aborted(signal)
        return artifacts

    async def listGenerations(self, signal=None):
        selected = []
        for project in await self._run(self._projects):
            for directory in await self._run(self._sessions,project):
                throw_aborted(signal)
                value = await self._run(self._resolve_generation,directory)
                if value is not None:
                    selected.append(value)
        return selected

    async def historicalCorpusRevision(self, signal=None):
        paths = sorted(item['sourcePath'] for item in await self.listGenerations(signal))
        digest = hashlib.sha256()
        for path in paths:
            throw_aborted(signal)
            try:
                token = revision(await self._physical_identity(path))
            except FileNotFoundError:
                token = 'missing'
            digest.update(stringify_json([path,token]).encode('utf-8'))
        throw_aborted(signal)
        return digest.hexdigest()

    async def publishStoredMigration(self, session_id, stored):
        publication = stored['publication']
        try:
            identity = await publication['value'].publish()
        except Exception as error:
            if self.coldLogMemo.get(session_id) is stored:
                self.coldLogMemo.pop(session_id,None)
            raise self._generation_failure(session_id,publication['source'],error)
        published = dict(stored,status='current',revision=revision(identity))
        published.pop('publication',None)
        return self._memoize(session_id,published)

    async def readStoredLog(self, path, expected_id, signal=None):
        throw_aborted(signal)
        probe = await self._run(file_revision,path)
        memo = self._memo(expected_id,probe,'current')
        if memo is not None:
            return memo
        snapshot = await readStableJsonlFile(path,signal)
        data = snapshot['bytes']
        try:
            if self.compression=='zstd':
                parsed = await self._scan_current_zstd(data,signal)
            else:
                parsed = scanLog(data,self.format_version)
                parsed['recoveredTail'] = []
                if parsed['committedBytes']<len(data):
                    parsed['tornTruncateTo'] = parsed['committedBytes']
        except SessionFormatUnsupportedError as error:
            throw_aborted(signal)
            raise unsupported(str(error),dict(kind='jsonl',path=path))
        except Exception as error:
            throw_aborted(signal)
            raise SessionPersistenceCorruptionError('session "%s": stored log is corrupt: %s (raw log: %s)' % (expected_id,error_string(error),path),dict(cause=error)) from error
        throw_aborted(signal)
        await self._run(self._assert_identity,path,self.format_version,parsed['meta'],expected_id)
        throw_aborted(signal)
        assertStoredId(expected_id,parsed['meta'])
        validateStoredEvents(parsed['meta'],parsed['events'],dict(kind='jsonl',path=self.locate(parsed['meta'])),self.format_version)
        stored = dict(status='current',meta=parsed['meta'],eventState='shared-frozen',events=deep_freeze(parsed['events']),
                      inheritedEventCount=parsed['inheritedEventCount'],recoveredTail=parsed['recoveredTail'],revision=revision(snapshot['identity']))
        if parsed.get('tornTruncateTo') is not None:
            stored['tornTruncateTo'] = parsed['tornTruncateTo']
        return self._memoize(expected_id,stored)

    async def _scan_current_zstd(self, data, signal):
        throw_aborted(signal)
        structural = scan_frames(data)
        frames = structural['frames']
        if not frames:
            raise ValueError('empty or header-less Zstandard session log')
        first = frames[0]
        header = self._decode(data,first)
        self._header_frame(header)
        scanner = SessionLogScanner(header,format_version=self.format_version)
        deadline = time.monotonic()+0.5
        for frame in frames[1:]:
            throw_aborted(signal)
            scanner.write(self._decode(data,frame))
            if time.monotonic()>=deadline:
                await asyncio.sleep(0)
                deadline = time.monotonic()+0.5
        checkpoint = scanner.checkpoint()
        if checkpoint['committedBytes']!=checkpoint['inputBytes']:
            raise ValueError('corrupt Zstandard session log: complete frame contains a torn JSONL record')
        torn = structural.get('tornStart')
        if torn is None:
            return dict(scanner.finish(),recoveredTail=[])
        try:
            recovered = decompress_frame(data[torn:],incomplete=True)
        except Exception:
            throw_aborted(signal)
            recovered = b''
        scanner.write(recovered)
        parsed = scanner.finish()
        return dict(parsed,tornTruncateTo=torn,recoveredTail=parsed['events'][checkpoint['eventCount']:])

    async def resolveCurrentLog(self, session_id, signal=None):
        await self.ensureRootEncoding()
        selected = await self.findLog(session_id,signal)
        if selected is None or selected['sourceVersion']<self.format_version:
            return None
        if selected['sourceVersion']>self.format_version:
            raise unsupported(sessionFormatVersionRefusal(session_id,selected['sourceVersion'],self.format_version),dict(kind='jsonl',path=selected['sourcePath']))
        return selected['sourcePath']

    async def persistBatch(self, header, events, isMaterialized, inheritedEventCount):
        self.coldLogMemo.pop(header['id'],None)
        await self.ensureRootEncoding()
        if isMaterialized:
            await self._run(self._append,self.locate(header),self._event_frame(events))
        else:
            await self._run(self._materialize,header,inheritedEventCount,events)
            self.tracker.materialized(header['id'])

    async def persistHeader(self, header, inheritedEventCount):
        self.coldLogMemo.pop(header['id'],None)
        await self.ensureRootEncoding()
        await self._run(self._materialize,header,inheritedEventCount,[])
        self.tracker.materialized(header['id'])

    def _event_frame(self, events):
        content = (eventLines(events,self.format_version)+'\n').encode('utf-8')
        return compress_frame(content) if self.compression=='zstd' else content

    def _materialize(self, header, cut, events):
        path = self.locate(header)
        directory = os.path.dirname(path)
        opposite = self._opposite_generation(directory)
        if opposite is not None:
            raise self._encoding_error(opposite)
        content = header_bytes(header,cut,self.format_version)
        if self.compression=='zstd':
            content = compress_frame(content)
        if events:
            content += self._event_frame(events)
        ensure_durable_directory(filesystem_path(directory))
        if self._resolve_generation(directory) is not None:
            raise ValueError('refusing to materialize "%s": a log already exists on disk (open it instead)' % header['id'])
        descriptor,staging = tempfile.mkstemp(prefix=os.path.basename(path)+'.',suffix='.tmp',dir=filesystem_path(directory))
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            publish_new_file(staging,path)
        except BaseException:
            os.unlink(staging)
            raise
        if os.name!='nt':
            discard_staging(staging)

    async def truncateTornTail(self, header, truncateTo):
        self.coldLogMemo.pop(header['id'],None)
        await self._run(self._truncate,self.locate(header),truncateTo)
        if self.ctx is not None:
            self.ctx.logger.warn('%s: session "%s" recovered from a torn tail; incomplete tail bytes were discarded' % (self.name,header['id']))

    def hasPendingSession(self, session_id):
        return self.tracker.hasPending(session_id)

    def releaseHandle(self, handle, materialized):
        self.tracker.release(handle,materialized)

    async def acquireWriteLease(self, header):
        directory = sessionDir(self.root,field(header,'cwd'),header['id'])
        opposite = await self._run(self._opposite_generation,directory)
        if opposite is not None:
            raise self._encoding_error(opposite)
        return await SessionWriteLease.acquire(directory,header['id'])


from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema


class CurrentJsonlSessionPersistencePlugin(Plugin):
    """Explicit candidate mount; registry switching belongs to the consumer batch."""
    id = 'session-persistence-jsonl'
    name = '@deepseek-ai/dsh-session-persistence-jsonl'
    Config = Schema.object({'root':Schema.string().required(),
                            'compression':Schema.union(['zstd','none']).default('zstd')})

    def apply(self, ctx):
        persistence = CurrentJsonlSessionPersistence(self.config['root'],self.config.get('compression','zstd'),ctx)
        ctx.set_service('sessionPersistence',persistence)
        ctx.set_service('session_persistence',persistence)
