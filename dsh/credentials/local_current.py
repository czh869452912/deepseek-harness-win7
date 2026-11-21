"""Current credential document ownership and serialized durable mutations."""
import asyncio
import errno
import json
import os
from pathlib import Path

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.environment import resolve_dsh_home
from dsh.cordis.file_lock import with_file_lock
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED
from dsh.credentials.credentials import CredentialProvider
from dsh.credentials.credentials_local import (CredentialsService, assert_owner_only,
    assert_json_value, assert_storable_api_key)
from dsh.credentials.document_current import parse_credentials_document, render_flat_layout_migration
from dsh.credentials.editor_current import render_edit
from dsh.util.atomic_write import write_file_atomic


Config = Schema.object({
    'path': Schema.string(), 'dshHome': Schema.string(),
    'watch': Schema.boolean().default(True),
    'debounceMs': Schema.number().min(0).default(100),
})


class CurrentLocalCredentialProvider(CredentialProvider):
    # These reference-layer methods contain no storage or lifecycle effects.
    _environment_entry = CredentialsService._environment_entry
    _inherited = CredentialsService._inherited
    _dotenv_fallback = CredentialsService._dotenv_fallback
    resolve = CredentialsService.resolve
    describe = CredentialsService.describe
    describe_record = CredentialsService.describe_record
    list_records = CredentialsService.list_records

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        cfg = config or {}
        configured_path = cfg.get('path')
        self.filepath = os.path.abspath(configured_path if configured_path is not None else os.path.join(
            resolve_dsh_home(cfg.get('dshHome')), '.credentials.yaml'))
        self._credentials, self._records = {}, {}
        self.text = None
        self.closed = False
        self._tail = None
        self._watcher = None
        self._stop = asyncio.Event()
        self.watch = cfg.get('watch', True)
        self.debounce = cfg.get('debounceMs', 100) / 1000.0

    def _read(self):
        assert_owner_only(self.filepath)
        try: return Path(self.filepath).read_bytes().decode('utf-8')
        except FileNotFoundError: return None

    def _warn(self, *args):
        logger = getattr(self.ctx, 'logger', None)
        if logger is not None: logger.warn(*args)

    def _parse(self, text):
        document = (dict(refs={}, records={}, ignoredKeys=[]) if text is None
                    else parse_credentials_document(text, self.filepath))
        if document['ignoredKeys']:
            names = ', '.join(json.dumps(key, ensure_ascii=False) for key in document['ignoredKeys'])
            self._warn('credentials-local: ignoring unknown top-level keys %s in %s; '
                       'only `refs` and `records` entries resolve', names, self.filepath)
        return document

    async def initialize(self):
        text = self._read()
        if text is not None and render_flat_layout_migration(text) is not None:
            async def migrate():
                current = self._read()
                if current is None: raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), self.filepath)
                migrated = render_flat_layout_migration(current)
                if migrated is None: return current
                await write_file_atomic(self.filepath, migrated, mode=0o600, dir_mode=0o700)
                logger = getattr(self.ctx, 'logger', None)
                if logger is not None:
                    logger.info('credentials-local: migrated %s to the version %d layout; values are unchanged', self.filepath, 1)
                return migrated
            text = await with_file_lock(self.filepath, migrate, waitMs=30000, legacy_windows_marker=True)
        document = self._parse(text)
        self.text, self._credentials, self._records = text, document['refs'], document['records']
        if self.watch:
            self._watcher = asyncio.ensure_future(self._watch())

    def _enqueue(self, operation):
        previous = self._tail
        async def run():
            if previous is not None:
                try: await asyncio.shield(previous)
                except Exception: pass
            return await operation()
        task = asyncio.ensure_future(run())
        # A caller abandoning its result must not strand the queue or produce
        # an unhandled background exception. Awaiting task still raises it.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        self._tail = task
        return asyncio.shield(task)

    async def reconcile_from_disk(self):
        text = self._read()
        if text == self.text or self.closed: return
        document = self._parse(text)
        refs, records = document['refs'], document['records']
        changed_refs = [key for key in dict.fromkeys(list(self._credentials)+list(refs))
                        if self._credentials.get(key, _UNDEFINED) != refs.get(key, _UNDEFINED)]
        changed_records = [key for key in dict.fromkeys(list(self._records)+list(records))
                           if self._records.get(key, _UNDEFINED) != records.get(key, _UNDEFINED)]
        self.text, self._credentials, self._records = text, refs, records
        for key in changed_refs: self.notify_updated(key)
        for key in changed_records: self.notify_record_updated(key)

    async def refresh(self):
        if self.closed: return
        try: await self.reconcile_from_disk()
        except Exception as error:
            self._warn('credentials-local: reload failed at %s; keeping the last good document', self.filepath)
            self._warn(error)

    def queue_refresh(self):
        if not self.closed: return self._enqueue(self.refresh)

    async def _watch(self):
        # Polling supports Windows 7 without a native filesystem watcher.
        # Compare content as well as stat: editors can retain mtime and size.
        self.queue_refresh()  # close initial-load/watcher-start gap
        marker, stable_since, observed = _UNDEFINED, 0.0, _UNDEFINED
        loop = asyncio.get_running_loop()
        interval = max(0.001, min(self.debounce, 0.010))
        while not self.closed:
            try:
                current = self._read()
                if current != marker:
                    marker, stable_since = current, loop.time()
                if current != observed and loop.time()-stable_since >= self.debounce:
                    observed = current
                    self.queue_refresh()
            except Exception as error:
                self._warn('credentials-local: watcher error on %s', self.filepath)
                self._warn(error)
            try: await asyncio.wait_for(self._stop.wait(), interval)
            except asyncio.TimeoutError: pass

    def read_record(self, key):
        return self._records.get(key)

    def _mutation(self, key, action, operation):
        if self.closed:
            async def rejected():
                raise RuntimeError('credentials-local is disposed: cannot '+action+' "'+key+'"')
            return asyncio.ensure_future(rejected())
        async def queued():
            if self.closed:
                raise RuntimeError('credentials-local was disposed before the queued "'+key+'" '+action+' ran')
            os.makedirs(os.path.dirname(self.filepath), mode=0o700, exist_ok=True)
            async def locked():
                await self.reconcile_from_disk()
                return await operation()
            return await with_file_lock(self.filepath, locked, waitMs=30000, legacy_windows_marker=True)
        return self._enqueue(queued)

    async def _commit(self, section, key, value):
        text = render_edit(self.text, section, key, value)
        await write_file_atomic(self.filepath, text, mode=0o600, dir_mode=0o700)
        self.text = text
        mapping = self._credentials if section == 'refs' else self._records
        if value is _UNDEFINED: mapping.pop(key, None)
        else: mapping[key] = value
        if section == 'refs': self.notify_updated(key)
        else: self.notify_record_updated(key)

    def set(self, ref, value):
        if len(value) == 0:
            async def rejected():
                raise ValueError('credentials-local: an empty value cannot be stored for "'+ref+'"; use unset')
            return asyncio.ensure_future(rejected())
        return self._mutation(ref, 'set', lambda: self._commit('refs', ref, value))

    def unset(self, ref):
        async def operation():
            if ref in self._credentials: await self._commit('refs', ref, _UNDEFINED)
        return self._mutation(ref, 'unset', operation)

    def modify_record(self, key, mutate):
        async def operation():
            current = self._records.get(key)
            value = await await_callback_result(mutate(current))
            if value is None or value is _UNDEFINED: return current
            if value.get('kind') == 'grant': assert_json_value('record "'+key+'" payload', value.get('payload', _UNDEFINED))
            else: assert_storable_api_key(key, value)
            await self._commit('records', key, value)
            return value
        return self._mutation(key, 'modify', operation)

    def delete_record(self, key):
        async def operation():
            if key in self._records: await self._commit('records', key, _UNDEFINED)
        return self._mutation(key, 'delete', operation)

    def deleteRecord(self, key):
        return self.delete_record(key)

    async def dispose(self):
        self.closed = True
        self._stop.set()
        if self._watcher is not None: await self._watcher
        if self._tail is not None:
            try: await asyncio.shield(self._tail)
            except Exception: pass


class CurrentCredentialsLocalPlugin(Plugin):
    id = 'credentials-local'
    name = '@deepseek-ai/dsh-credentials-local'
    Config = Config

    async def apply(self, ctx):
        service = CurrentLocalCredentialProvider(ctx, self.config)
        ctx.effect(lambda: service.dispose)
        await service.initialize()
