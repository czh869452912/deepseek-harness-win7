"""Separately owned storage providers for canonical bundle composition."""
from dsh.cordis.plugin import Plugin
from dsh.storage.storage_json import JsonStorageBackend
from dsh.storage.domain_impl import DomainFacility


class StorageJsonPlugin(Plugin):
    id = "storage-json"
    inject = ["storage"]

    def apply(self, ctx):
        root = self.config.get("root")
        if not isinstance(root, str) or not root:
            raise ValueError("storage-json requires root")
        backend = JsonStorageBackend(root)
        unregister = ctx.get("storage").backend.register("json", backend)
        ctx.set_service("storageBackend:json", backend)

        async def close():
            unregister()
            await backend.close()

        ctx.effect(lambda: close)


class StorageDomainPlugin(Plugin):
    id = "storage-domain"
    inject = ["storage", "storageBackend:json"]

    def apply(self, ctx):
        facility = DomainFacility(ctx, self.config)
        unmount = ctx.get("storage").mount("domain", facility)
        ctx.set_service("storageDomain", facility)

        async def close():
            await facility.close_all()
            unmount()

        ctx.effect(lambda: close)
