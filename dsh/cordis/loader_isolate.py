"""Loader-owned service isolation realms and context patch hooks."""

from typing import Any, Dict, Optional


class Realm:
    def __init__(self) -> None:
        self.store: Dict[str, Any] = {}

    @property
    def suffix(self) -> str:
        raise NotImplementedError

    def access(self, key: str, create: bool = False) -> Any:
        if key in self.store:
            return self.store[key]
        token = _RealmToken("%s%s" % (key, self.suffix))
        if create:
            self.store[key] = token
        return token

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    @property
    def size(self) -> int:
        return len(self.store)


class _RealmToken:
    def __init__(self, description: str):
        self.description = description

    def __repr__(self) -> str:
        return "<LoaderRealm %s>" % self.description


class LocalRealm(Realm):
    def __init__(self, entry: Any):
        super().__init__()
        self.entry = entry

    @property
    def suffix(self) -> str:
        return "#%s" % self.entry.options.get("id", "")


class GlobalRealm(Realm):
    def __init__(self, label: str):
        super().__init__()
        self.label = label

    @property
    def suffix(self) -> str:
        return "@%s" % self.label


class IsolateManager:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.realms: Dict[str, GlobalRealm] = {}
        ctx.on("loader/entry-init", self._entry_init, global_listener=True)
        ctx.on("loader/patch-context", self._patch_context, global_listener=True)
        ctx.on("loader/partial-dispose", self._partial_dispose, global_listener=True)

    def _entry_init(self, entry: Any) -> None:
        entry.ctx._isolated_keys = dict(entry.ctx._isolated_keys)
        entry.ctx._intercept_map = dict(entry.ctx._intercept_map)

    @staticmethod
    def _belongs_to(ctx: Any, ancestor: Any) -> bool:
        current = ctx
        while current is not None:
            if current is ancestor:
                return True
            current = getattr(current, "_parent", None)
        return False

    def _notify_diff(self, changes: Dict[str, Any]) -> None:
        registry = self.ctx.registry
        for fiber in list(registry.list_fibers()):
            inject = getattr(fiber, "inject", {})
            for name, keys in changes.items():
                if name not in inject:
                    continue
                key = getattr(fiber.ctx, "_isolated_keys", {}).get(name, name)
                if key in keys:
                    registry.refresh_fiber(fiber)
                    break

    def _access(self, entry: Any, name: str, create: bool = False) -> Optional[Any]:
        isolate = entry.options.get("isolate") or {}
        label = isolate.get(name)
        if not label:
            return None
        if label is True:
            if entry.realm is None:
                entry.realm = LocalRealm(entry)
            return entry.realm.access(name, create)
        realm = self.realms.get(label)
        if realm is None and create:
            realm = self.realms[label] = GlobalRealm(label)
        return realm.access(name, create) if realm is not None else None

    async def _patch_context(self, entry: Any, next_fn: Any) -> Any:
        parent = entry.parent.ctx
        isolated = dict(parent._isolated_keys)
        for name in (entry.options.get("isolate") or {}):
            isolated[name] = self._access(entry, name, True)
        previous = dict(entry.ctx._isolated_keys)
        names = set(previous) | set(isolated)
        changes = {}
        for name in names:
            old_key = previous.get(name, name)
            new_key = isolated.get(name, name)
            if old_key != new_key:
                changes[name] = (old_key, new_key)

        entry.ctx._isolated_keys = isolated
        intercepted = dict(parent._intercept_map)
        intercepted.update(entry.options.get("intercept") or {})
        entry.ctx._intercept_map = intercepted
        entry.ctx._own_intercepts = dict(entry.options.get("intercept") or {})
        if entry.fiber is not None:
            entry.fiber.ctx._isolated_keys = dict(isolated)
            entry.fiber.ctx._intercept_map = dict(intercepted)
        result = await next_fn()

        store = entry.ctx.reflect.store
        for old_key, new_key in changes.values():
            impl = store.get(old_key)
            if impl is None or store.get(new_key) is not None:
                continue
            provider_ctx = getattr(getattr(impl, "fiber", None), "ctx", None)
            if not self._belongs_to(provider_ctx, entry.ctx):
                continue
            store[new_key] = impl
            if store.get(old_key) is impl:
                del store[old_key]

        if changes:
            self._notify_diff(changes)
        return result

    def _partial_dispose(self, entry: Any, legacy: Dict[str, Any], active: bool) -> None:
        for name, label in (legacy.get("isolate") or {}).items():
            if label is True:
                continue
            if active and (entry.options.get("isolate") or {}).get(name) == label:
                continue
            realm = self.realms.get(label)
            if realm is None:
                continue
            for candidate in self.ctx.get("loader").entries():
                if (candidate.options.get("isolate") or {}).get(name) == label:
                    break
            else:
                realm.delete(name)
                if not realm.size:
                    self.realms.pop(label, None)


def install_isolate(ctx: Any) -> IsolateManager:
    return IsolateManager(ctx)


__all__ = ["GlobalRealm", "IsolateManager", "LocalRealm", "Realm", "install_isolate"]
