"""Named provider seam with publication-owned one-shot runs."""
import asyncio
import uuid

from dsh.typert.remote import TypertRemoteService
from dsh.core.notifications import emit_contained
from dsh.core.tools import _assert_supported_schema
from dsh.subagent.composition import valid_depth
from dsh.subagent.descriptor import snapshot_descriptor
from dsh.subagent.errors import SubagentError
from dsh.cordis.plugin import Plugin
from dsh.subagent.setup_registry import SetupRegistry


class SubagentRuntime(TypertRemoteService):
    def __init__(self, ctx):
        super().__init__(ctx, "subagents")
        self.providers = {}
        self.activation_setups = SetupRegistry()
        self.continuations = None

    def continuation_manager(self):
        if self.continuations is None:
            from dsh.subagent.continuation import ContinuationManager
            self.continuations = ContinuationManager(self.ctx, self, self.activation_setups)
        return self.continuations

    def activationSetup(self, contribution):
        return self.ctx.effect(lambda: self.activation_setups.register(contribution), 'subagents.activationSetup()')

    registerContinuableSetup = activationSetup

    async def listChildren(self, parent_session_id, signal=None):
        from dsh.subagent.listing import list_children
        return await list_children(self.ctx, parent_session_id, signal)

    async def listDescendants(self, root_session_id, signal=None):
        from dsh.subagent.listing import list_children
        return await list_children(self.ctx, root_session_id, signal, descendants=True)

    async def startContinuable(self, spec):
        return await self.continuation_manager().start(spec)

    async def followup(self, parent, child_id, content, options=None):
        return await self.continuation_manager().followup(parent, child_id, content, options)

    def reportFrom(self, child, content, options=None):
        return self.continuation_manager().report(child, content, options)

    def interrupt(self, child_id, authority):
        self.continuation_manager().interrupt(child_id, authority)

    async def drainContinuableDescendants(self, parents):
        await self.continuation_manager().drain_descendants(parents)

    async def drainContinuableChildren(self, parent, child_ids):
        await self.continuation_manager().drain_children(parent, child_ids)

    def registerProvider(self, provider):
        def setup():
            if provider.name in self.providers:
                raise SubagentError('a subagent provider named "{}" is already registered'.format(provider.name), "DUPLICATE_PROVIDER")
            self.providers[provider.name] = provider
            def cleanup():
                self.providers.pop(provider.name, None)
                emit_contained(self.ctx, "subagent/provider-removed", provider.name)
            yield cleanup
            self.ctx.emit("subagent/provider-added", provider)
        return self.ctx.effect(setup, "subagents.registerProvider()")

    def getProvider(self, name):
        return self.providers.get(name)

    def list(self):
        return list(self.providers)

    def expect_provider(self, name):
        provider = self.getProvider(name)
        if provider is None:
            raise SubagentError('no subagent provider registered for "{}"'.format(name), "NO_PROVIDER")
        return provider

    async def start(self, name, request):
        provider = self.expect_provider(name)
        for field, capability in (("agentOptions", "agentOptions"), ("outputSchema", "outputSchema"),
                                  ("maxDepth", "depthLimit"), ("toolFilter", "toolFilter"), ("persona", "persona")):
            if field in request and not provider.capabilities.get(capability):
                raise SubagentError('subagent provider "{}" does not support the "{}" capability'.format(name, capability), "UNSUPPORTED_CAPABILITY")
        if "maxDepth" in request:
            valid_depth(request["maxDepth"])
        if "outputSchema" in request:
            schema = request["outputSchema"]
            _assert_supported_schema(schema)
            if schema.get("type") != "object":
                raise TypeError("subagent outputSchema must be an object schema")
        descriptor = snapshot_descriptor(dict({"mode": "one-shot", "provider": name},
                                             **({"label": request["label"]} if "label" in request else {})))
        run = await provider.start(dict(request, descriptor=descriptor))
        identity = {"runId": str(uuid.uuid4()), "provider": name, "id": run.id, "local": getattr(run, "localAgent", None) is not None}
        def settled(future):
            info = dict(identity)
            try:
                result = future.result()
                info["stopReason"] = result["stopReason"]
                if result["output"]:
                    info["lastAssistantMessage"] = result["output"]
            except BaseException:
                info["stopReason"] = "error"
            emit_contained(self.ctx, "subagent/end", info, request["parent"], self)
        run.result.add_done_callback(settled)
        emit_contained(self.ctx, "subagent/start", identity, request["parent"], self)
        return run


async def settle_run(run):
    try:
        result = await run.result
        reason = result["stopReason"]
        if reason == "completed":
            outcome = {"status": "completed", "output": "".join(block["text"] for block in result["output"] if block["type"] == "text")}
        elif reason == "aborted" and "diagnostic" not in result:
            outcome = {"status": "killed"}
        else:
            outcome = {"status": "failed", "detail": reason + ("; diagnostic: " + result["diagnostic"] if "diagnostic" in result else "")}
    except Exception as error:
        outcome = {"status": "failed", "detail": str(error)}
    try:
        await run.dispose()
    except Exception as error:
        return {"status": "failed", "detail": (outcome["detail"] + "; " if "detail" in outcome else "") + "dispose failed: " + str(error)}
    return outcome


class SubagentPlugin(Plugin):
    id = 'subagent'
    inject = ['agents']

    def apply(self, ctx):
        service = SubagentRuntime(ctx)
        service.continuation_manager()
        ctx.set_service('subagents', service)
        def projections(child_ctx):
            from dsh.subagent.projections import IDENTITY, TIMING
            child_ctx.get('sessionProjections').register(IDENTITY)
            child_ctx.get('sessionProjections').register(TIMING)
        ctx.inject(['sessionProjections'], projections)
