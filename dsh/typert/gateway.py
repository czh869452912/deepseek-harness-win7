"""Canonical Typert Gateway: Connection RPC plus WebSocket streams/events."""
from types import SimpleNamespace

from dsh.cordis.service import Service
from dsh.typert.artifact import UNDEFINED
from dsh.typert.dispatch import RemoteDispatcher, remote_request, rpc_failure
from dsh.typert.remote_events import RemoteEvents
from dsh.typert.stream_mux import RemoteStreamMux, reject_upgrade


class TypertGatewayService(Service):
    inject = ["typert"]

    def __init__(self, ctx, config=None):
        interval = (config or {}).get("websocketHeartbeatIntervalMs", 30000)
        if type(interval) is not int or not 1 <= interval <= 2147483647:
            raise ValueError("websocketHeartbeatIntervalMs must be an integer in timer range")
        super().__init__(ctx, "typertGateway")
        self.dispatcher, self.events = RemoteDispatcher(ctx), RemoteEvents(ctx)
        self.wireStream = SimpleNamespace(open=self.open_wire_stream, failure=lambda error: rpc_failure(error)["error"])
        ctx.effect(lambda: self.events.close, "Gateway event lifecycle")
        def rpc(child):
            child.get("connection").rpc.intercept("/api", self.claims_endpoint, self.dispatch_rpc)
        ctx.inject(["connection"], rpc)
        def websocket(child):
            mux = RemoteStreamMux(self.open_wire_stream, self.wireStream.failure, interval)
            async def upgrade(request, writer):
                rejection = child.get("connection").request_rejection(request)
                if rejection is not None:
                    await reject_upgrade(writer, rejection)
                    return
                await mux.upgrade(request, writer)
            def setup():
                undo = child.get("webServer").register_upgrade("/api/remote.mux", upgrade)
                async def close():
                    undo()
                    await mux.close()
                return close
            child.effect(setup, "Gateway WebSocket mux")
        ctx.inject(["connection", "webServer"], websocket)

    def claims_endpoint(self, endpoint):
        return endpoint == "$events/result" or self.dispatcher.claims_endpoint(endpoint)

    async def invoke(self, request):
        return await self.dispatcher.invoke(request)

    async def stream(self, request):
        return await self.dispatcher.stream(request)

    async def dispatch_rpc(self, endpoint, payload, signal):
        try:
            if endpoint == "$events/result":
                self.events.result(payload)
                value = UNDEFINED
            else:
                value = await self.invoke(remote_request(endpoint, payload, signal))
            return {"ok": True, "value": value}
        except Exception as error:
            return rpc_failure(error)

    async def open_wire_stream(self, endpoint, payload, signal):
        if endpoint == "$events":
            return self.events.open(payload, signal)
        return await self.stream(remote_request(endpoint, payload, signal))

    def registerRemoteEvents(self, source, host):
        return self.events.register(source, host)
