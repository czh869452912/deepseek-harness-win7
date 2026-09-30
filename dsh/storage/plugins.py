"""Separately owned storage providers for canonical bundle composition."""
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
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
    inject = ["storage"]
    Config = Schema.object({
        "backend": Schema.string().required(),
        "routes": Schema.dict(Schema.string()).default({}),
    })

    async def apply(self, ctx):
        backends = dict.fromkeys([self.config["backend"]] + list(self.config["routes"].values()))

        def mount(domain_ctx):
            facility = DomainFacility(domain_ctx, self.config)
            unmount = domain_ctx.get("storage").mount("domain", facility)
            domain_ctx.set_service("storageDomain", facility)

            async def close():
                await facility.close_all()
                unmount()

            domain_ctx.effect(lambda: close)

        await ctx.inject(["storageBackend:" + name for name in backends], mount)
