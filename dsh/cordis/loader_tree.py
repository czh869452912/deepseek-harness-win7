"""Mutable loader entry tree translated from vendor/loader config/tree.ts."""

import asyncio
import inspect
import secrets
from typing import Any, Dict, Iterator, List, Optional

from dsh.cordis.loader_group import EntryGroup, LoaderAggregateError


class EntryCollection:
    """Upstream callable iterator with legacy list-style access."""

    def __init__(self, tree: "EntryTree"):
        self.tree = tree

    def __call__(self) -> Iterator[Any]:
        return self.tree._iter_entries()

    def __iter__(self) -> Iterator[Any]:
        return self.tree._iter_entries()

    def __len__(self) -> int:
        return sum(1 for _ in self.tree._iter_entries())

    def __getitem__(self, index: int) -> Any:
        return list(self.tree._iter_entries())[index]


class EntryTree:
    sep = ":"

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.enable_logs: Optional[bool] = None
        self.store: Dict[str, Any] = {}
        self.root = EntryGroup(self.ctx, self)
        self.entries = EntryCollection(self)
        owner_entry = getattr(ctx, "_loader_entry", None)
        if owner_entry is not None:
            owner_entry.subtree = self

    @property
    def context(self) -> Any:
        return self.ctx

    def _iter_entries(self) -> Iterator[Any]:
        for entry in list(self.store.values()):
            yield entry
            if entry.subtree is not None:
                for nested in entry.subtree.entries():
                    yield nested

    def get_tasks(self) -> List[Any]:
        tasks = []
        for entry in self.entries():
            task = entry._init_task or (entry.fiber.inertia if entry.fiber is not None else None)
            if task is not None:
                tasks.append(task)
        return tasks

    getTasks = get_tasks

    async def wait(self) -> None:
        while True:
            tasks = self.get_tasks()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                continue
            outcomes = await asyncio.gather(
                *(entry._await_fiber() for entry in self.entries()),
                return_exceptions=True
            )
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            if len(failures) == 1:
                raise failures[0]
            if failures:
                raise LoaderAggregateError(failures, "loader fibers failed")
            affected = self.ctx.reflect.notify(["loader"])
            if affected:
                await asyncio.gather(*(fiber.wait() for fiber in affected))
            if not self.get_tasks():
                return

    def __await__(self):
        return self.wait().__await__()

    def ensure_id(self, options: Dict[str, Any]) -> str:
        if not options.get("id"):
            while True:
                entry_id = secrets.token_hex(4)
                if entry_id not in self.store:
                    options["id"] = entry_id
                    break
        return options["id"]

    ensureId = ensure_id

    def resolve(self, entry_id: str) -> Any:
        parts = entry_id.split(self.sep)
        tree: EntryTree = self
        current = None
        for index, part in enumerate(parts):
            current = tree.store.get(part)
            if current is None:
                raise RuntimeError("cannot resolve entry %s" % entry_id)
            if index < len(parts) - 1:
                if current.subtree is not None:
                    tree = current.subtree
                elif current.subgroup is not None:
                    tree = current.subgroup.tree
                else:
                    raise RuntimeError("cannot resolve entry %s" % entry_id)
        return current

    def resolve_group(self, entry_id: Optional[str]) -> EntryGroup:
        if not entry_id:
            return self.root
        entry = self.resolve(entry_id)
        if entry.subgroup is None:
            raise RuntimeError("entry %s is not a group" % entry_id)
        return entry.subgroup

    resolveGroup = resolve_group

    async def create(self, options: Dict[str, Any], parent: Optional[str] = None,
                     position: Optional[int] = None) -> str:
        group = self.resolve_group(parent)
        entry_id = await group.create(options)
        entry = self.resolve(entry_id)
        insert_at = len(group.data) if position is None else min(position, len(group.data))
        group.data.insert(insert_at, entry.options)
        value = group.tree.write()
        if inspect.isawaitable(value):
            await value
        return entry_id

    async def remove(self, entry_id: str) -> None:
        entry = self.resolve(entry_id)
        group = entry.parent
        await group.remove(entry.options["id"])
        value = group.tree.write()
        if inspect.isawaitable(value):
            await value

    async def update(self, entry_id: str, options: Dict[str, Any],
                     parent: Any = ..., position: Optional[int] = None) -> None:
        entry = self.resolve(entry_id)
        source = entry.parent
        try:
            source_index = source.data.index(entry.options)
        except ValueError:
            source_index = len(source.data)
        target = source
        moved = parent is not ...
        if moved:
            target = self.resolve_group(parent)
            source.unlink(entry.options)
            insert_at = len(target.data) if position is None else min(position, len(target.data))
            target.data.insert(insert_at, entry.options)
            entry.parent = target
        try:
            await entry.update(options, force=True)
        except BaseException as error:
            if moved:
                target.unlink(entry.options)
                source.data.insert(min(source_index, len(source.data)), entry.options)
                entry.parent = source
                try:
                    await entry.update({}, force=True)
                except BaseException as rollback_error:
                    raise LoaderAggregateError(
                        [error, rollback_error],
                        "failed to roll back loader entry move %s" % entry_id,
                    )
            raise
        first = source.tree.write()
        if inspect.isawaitable(first):
            await first
        if target is not source:
            second = target.tree.write()
            if inspect.isawaitable(second):
                await second

    def import_plugin(self, name: str) -> Any:
        return self.ctx.get("loader").import_plugin(name)

    def write(self) -> None:
        raise NotImplementedError


__all__ = ["EntryCollection", "EntryTree"]
