"""Nested loader entry groups translated from vendor/loader config/group.ts."""

import asyncio
from typing import Any, Dict, List, Optional

from dsh.cordis.loader_entry import Entry
from dsh.cordis.plugin import Plugin


class LoaderAggregateError(RuntimeError):
    def __init__(self, errors: List[BaseException], message: str):
        super().__init__(message + ": " + "; ".join(str(error) for error in errors))
        self.errors = errors


class EntryGroup:
    key = "_cordis_entry_group"

    def __init__(self, ctx: Any, tree: Any, owner_entry: Optional[Entry] = None):
        self.ctx = ctx
        self.tree = tree
        self.owner_entry = owner_entry
        self.data: List[Dict[str, Any]] = []
        if owner_entry is not None:
            owner_entry.subgroup = self

    @property
    def context(self) -> Any:
        return self.ctx

    async def create(self, options: Dict[str, Any]) -> str:
        entry_id = self.tree.ensure_id(options)
        existing = self.tree.store.get(entry_id)
        entry = existing or Entry(self.ctx.get("loader"), base_ctx=self.ctx)
        if existing is None:
            self.tree.store[entry_id] = entry
        previous_parent = entry.parent
        entry.parent = self
        try:
            await entry.update(options, create=True, force=True)
        except BaseException:
            if existing is not None:
                entry.parent = previous_parent
            else:
                self.tree.store.pop(entry_id, None)
            raise
        return entry.id

    def unlink(self, options: Dict[str, Any]) -> None:
        for index, candidate in enumerate(self.data):
            if candidate is options:
                self.data.pop(index)
                return

    async def remove(self, entry_id: str, is_dispose: bool = False) -> None:
        local_id = entry_id.rsplit(self.tree.sep, 1)[-1]
        entry = self.tree.store.get(local_id)
        if entry is None:
            return
        await entry._dispose()
        if not is_dispose:
            self.unlink(entry.options)
        self.tree.store.pop(local_id, None)
        self.context.emit("loader/partial-dispose", entry, entry.options, False)

    async def update(self, config: List[Dict[str, Any]]) -> None:
        rows = config if isinstance(config, list) else []
        seen = set()
        for options in rows:
            entry_id = self.tree.ensure_id(options)
            if entry_id in seen:
                raise TypeError("duplicate loader entry id: %s" % entry_id)
            seen.add(entry_id)
        old_config = self.data
        old_map = {item["id"]: item for item in old_config}
        new_map = {item["id"]: item for item in rows}
        tasks = [asyncio.ensure_future(self.create(options)) for options in rows]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        if getattr(self.ctx.fiber, "uid", None) is None:
            return
        failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        try:
            if len(failures) == 1:
                raise failures[0]
            if failures:
                raise LoaderAggregateError(failures, "loader entries failed to apply")
            for entry_id in list(old_map):
                if entry_id not in new_map:
                    await self.remove(entry_id, True)
            self.data = rows
        except BaseException as error:
            rollback_errors = []
            for entry_id in reversed(list(new_map)):
                if entry_id in old_map:
                    continue
                try:
                    await self.remove(entry_id, True)
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
            for options in old_config:
                try:
                    await self.create(options)
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
            self.data = old_config
            if rollback_errors:
                raise LoaderAggregateError([error] + rollback_errors, "loader entry rollback failed")
            raise

    async def stop(self) -> None:
        for options in list(self.data):
            await self.remove(options["id"], True)


class Group(Plugin):
    name = "cordis:group"
    _cordis_entry_group = True
    initial: List[Dict[str, Any]] = []

    def __init__(self, config: Optional[Any] = None):
        super().__init__({})
        self.rows = config if isinstance(config, list) else []
        self.group: Optional[EntryGroup] = None

    async def apply(self, ctx: Any) -> Any:
        parent_ctx = getattr(ctx, "_parent", None)
        entry = getattr(parent_ctx, Entry.key, None)
        if entry is None:
            raise RuntimeError("cordis:group must be mounted by a loader entry")
        self.group = EntryGroup(ctx, entry.parent.tree, owner_entry=entry)
        await self.group.update(self.rows)
        return self.group.stop


__all__ = ["EntryGroup", "Group", "LoaderAggregateError"]
