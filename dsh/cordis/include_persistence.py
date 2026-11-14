"""Serialized Include journal draining, independent from plugin application."""
import asyncio
import copy
import inspect
import os
import secrets
from typing import Any, Dict, List, Optional

from dsh.cordis import include_journal as journal_ops
from dsh.cordis.include_patch import PatchIndex, ensure_insert_ids, route_journal
from dsh.cordis.utils import deep_equal


class IncludePersistence:
    def _initialize_journal(self) -> None:
        self.journal: Dict[str, Any] = {}
        self.anonymous: Dict[str, Any] = {}
        self.dirtyRead = False
        self.dirtyWrite = False
        self._draining: Optional[Any] = None
        self._applyTask: Optional[Any] = None
        self._pendingTree: Optional[List[Dict[str, Any]]] = None
        self._disposed = False
        self.persistenceError: Optional[BaseException] = None
        ensure_insert_ids(self.config.get('patches'), lambda entry_id: entry_id in self.store)

    def _persistence_warn(self, message: str, *args: Any) -> None:
        self.ctx.root.logger('loader').warn(message, *args)

    def _assign_ids(self, data: List[Dict[str, Any]]) -> None:
        used = set(); pending = []
        def walk(entries: List[Dict[str, Any]], parent: Optional[str]) -> None:
            for options in entries:
                if options.get('id'):
                    used.add(options['id'])
                else:
                    pending.append((options, parent))
                if options.get('group') and isinstance(options.get('config'), list):
                    walk(options['config'], options.get('id'))
        walk(data, None)
        previous = dict(self.anonymous)
        self.anonymous = {}
        for options, parent in pending:
            entry_id = None
            for candidate, info in list(previous.items()):
                if info['parent'] == parent and deep_equal(info['options'], options):
                    entry_id = candidate
                    previous.pop(candidate)
                    break
            if not entry_id:
                while True:
                    entry_id = secrets.token_hex(4)
                    if entry_id not in used and entry_id not in self.store:
                        break
            used.add(entry_id)
            self.anonymous[entry_id] = dict(parent=parent, options=copy.deepcopy(options))
            rest = dict(options); options.clear(); options['id'] = entry_id; options.update(rest)

    def _accept_snapshot(self, candidate: Dict[str, Any]) -> None:
        self._assign_ids(candidate['data'])
        if self.data is not None:
            index = PatchIndex(self.config.get('patches') or [])
            conflicts = journal_ops.reconcile(self.journal, journal_ops.flatten(self.data),
                                               journal_ops.flatten(candidate['data']), index.file_owned)
            for conflict in conflicts:
                self.ctx.logger('loader').error('config conflict in %s: entry %s %s; file wins',
                                               self.filename, conflict['id'], conflict['reason'])
        self.content = candidate['content']
        self.data = candidate['data']
        self._schedule_apply()
        if self.journal:
            self.dirtyWrite = True

    async def _journal_read(self) -> None:
        candidate = self._read_file()
        if candidate is not None:
            self._accept_snapshot(candidate)

    def _schedule_apply(self) -> None:
        if self._disposed or self.data is None:
            return
        tree = self.apply_patches(self.data, self.config.get('patches'))
        self._pendingTree = journal_ops.apply_journal(tree, self.journal, warn=self._persistence_warn)
        if self._applyTask is not None:
            return
        async def apply_latest() -> None:
            try:
                while self._pendingTree is not None:
                    tree = self._pendingTree
                    self._pendingTree = None
                    result = self.root.update(tree)
                    if inspect.isawaitable(result):
                        await result
            finally:
                self._applyTask = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(apply_latest())
        else:
            self._applyTask = loop.create_task(apply_latest())
            self._track(self._applyTask)

    def commit(self, change: Dict[str, Any]) -> None:
        self.ctx.emit('loader/config-update')
        group = change['group']
        parent = None if group is self.root else group.ctx.fiber.entry.options['id']
        journal_ops.record(self.journal, change, parent)
        self.dirtyWrite = True
        self._drain()

    def _drain(self) -> None:
        if self._draining is not None:
            return
        async def run() -> None:
            try:
                await self._journal_loop()
            finally:
                self._draining = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(run())
        else:
            self._draining = loop.create_task(run())

    async def _journal_loop(self) -> None:
        while self.dirtyRead or self.dirtyWrite:
            if self.dirtyRead:
                self.dirtyRead = False
                try:
                    await self._journal_read()
                except Exception as error:
                    self.persistenceError = error
                    self.ctx.logger('loader').warn(error)
                    if self.dirtyRead:
                        continue
                    return
            if self.dirtyWrite:
                self.dirtyWrite = False
                try:
                    await self._journal_write()
                except Exception as error:
                    self.persistenceError = error
                    self.ctx.logger('loader').error(error)

    async def _journal_write(self) -> None:
        if self.data is None or not self.journal:
            return
        try:
            with open(self.filename, 'r', encoding='utf-8', newline='') as stream:
                current = stream.read()
        except FileNotFoundError:
            self._persistence_warn('config file %s is missing, %d pending change(s) kept in memory',
                                   self.filename, len(self.journal))
            return
        if current != self.content:
            self.dirtyRead = self.dirtyWrite = True
            return
        batch = self.journal
        self.journal = {}
        def restore() -> None:
            for entry_id, value in self.journal.items():
                journal_ops.merge(batch, entry_id, value)
            self.journal = batch
        data = copy.deepcopy(self.data)
        patches = copy.deepcopy(self.config.get('patches') or [])
        if route_journal(batch, data, patches, self._persistence_warn):
            self.config = dict(self.config, patches=patches)
            if self.ctx.fiber.entry is not None:
                try:
                    result = self.ctx.fiber.update(self.config)
                    if inspect.isawaitable(result):
                        async def settle() -> None:
                            try:
                                await result
                            except Exception as error:
                                self.ctx.logger('loader').error(error)
                        task = asyncio.ensure_future(settle())
                        self._track(task)
                except Exception as error:
                    self.ctx.logger('loader').error(error)
            else:
                self._persistence_warn('patches of %s changed at runtime but cannot be persisted', self.filename)
        if deep_equal(data, self.data):
            self._schedule_apply()
            return
        text = self.dump(data)
        if not os.access(self.filename, os.W_OK):
            restore()
            self._persistence_warn('config file %s is read-only, %d pending change(s) kept in memory',
                                   self.filename, len(self.journal))
            return
        try:
            await self._write_text(text, self.content)
        except Exception as error:
            restore()
            from dsh.cordis.include import StaleWriteError
            if isinstance(error, StaleWriteError):
                self.dirtyRead = self.dirtyWrite = True
                return
            self._persistence_warn('failed to write config file %s, %d pending change(s) kept in memory',
                                   self.filename, len(self.journal))
            raise
        self.content = text
        self.data = data
        self._schedule_apply()

    async def flush(self) -> None:
        if self.journal and self._draining is None:
            self.dirtyWrite = True
            self._drain()
        while self._draining is not None or self._applyTask is not None:
            if self._draining is not None:
                await self._draining
            if self._applyTask is not None:
                await self._applyTask
        if self.journal:
            if self.persistenceError is not None:
                raise self.persistenceError
            raise RuntimeError('config file %s has %d unsaved change(s)' % (self.filename, len(self.journal)))
        self.persistenceError = None

    async def _refresh_journal(self) -> None:
        self.dirtyRead = True
        self._drain()
        await self.flush()

    async def _stop_journal(self) -> None:
        self._disposed = True
        self._pendingTree = None
        if self.journal:
            self.dirtyWrite = True
            self._drain()
        try:
            await self.flush()
        finally:
            result = self.root.stop()
            if inspect.isawaitable(result):
                await result
