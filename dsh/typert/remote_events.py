"""Gateway-owned event generations and scoped waterfall delivery ownership."""
import asyncio
import math
import uuid

from dsh.core.abort import AbortController, AbortSignal
from dsh.typert.artifact import UNDEFINED
from dsh.typert.dispatch import TypertGatewayError, RemoteInvocationCancelled, assert_json, cancellable_stream


def lossless(value):
    assert_json(value)
    def check(item):
        if type(item) is float and item == 0 and math.copysign(1, item) < 0:
            raise ValueError("negative zero is not lossless JSON")
        if isinstance(item, (dict, list)):
            for child in item.values() if isinstance(item, dict) else item:
                check(child)
    check(value)


def parse_result(value):
    if type(value) is not dict or set(value) != {"clientId", "eventId", "outcome"} or any(not isinstance(value[key], str) or not value[key] for key in ("clientId", "eventId")):
        raise ValueError("invalid Remote event result")
    outcome = value["outcome"]
    if type(outcome) is not dict:
        raise ValueError("invalid Remote event outcome")
    kind = outcome.get("kind")
    if kind == "next" and set(outcome) == {"kind"}:
        return value
    if kind == "result" and set(outcome) in ({"kind"}, {"kind", "value"}):
        if "value" in outcome:
            lossless(outcome["value"])
        return value
    if kind == "rejected" and set(outcome) == {"kind", "error"}:
        error = outcome["error"]
        if type(error) is not dict or not {"name", "message"}.issubset(error) or set(error) - {"name", "message", "code", "details"}:
            raise ValueError("invalid Remote event rejection")
        if not isinstance(error["name"], str) or not error["name"] or not isinstance(error["message"], str) or "code" in error and not isinstance(error["code"], str):
            raise ValueError("invalid Remote event rejection")
        if "details" in error:
            lossless(error["details"])
        return value
    raise ValueError("invalid Remote event outcome")


class EventQueue:
    def __init__(self):
        self.queue, self.closed = asyncio.Queue(), False

    def push(self, frame):
        if not self.closed:
            self.queue.put_nowait(frame)

    def end(self):
        self.closed = True
        self.queue.put_nowait(None)

    async def iterate(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item


class RemoteEvents:
    def __init__(self, ctx):
        self.ctx, self.registration, self.clients, self.pending = ctx, None, {}, {}

    def register(self, source, host):
        if self.registration is not None:
            raise ValueError("forwarded Remote event source already registered")
        controller = AbortController()
        stream = source(controller.signal)
        registration = {"controller": controller, "host": {"home": host["home"]}}
        self.registration = registration
        async def consume():
            try:
                async for dispatch in cancellable_stream(stream, "$events", controller.signal):
                    if "context" in dispatch:
                        self.start(dispatch)
                    else:
                        self.broadcast(dispatch)
                if not controller.signal.aborted:
                    raise ValueError("forwarded Remote event source ended unexpectedly")
            except Exception as error:
                if self.registration is registration and not controller.signal.aborted:
                    self.close_events(error)
                    self.registration = None
                    controller.abort(error)
        registration["done"] = asyncio.create_task(consume())
        async def dispose():
            if self.registration is registration:
                self.registration = None
                error = RuntimeError("forwarded Remote event source was removed")
                controller.abort(error)
                self.close_events(error)
            await registration["done"]
        return dispose

    async def close(self):
        registration = self.registration
        self.registration = None
        error = RuntimeError("Gateway disposed")
        self.close_events(error)
        if registration:
            registration["controller"].abort(error)
            await registration["done"]

    async def open(self, payload, signal):
        if type(payload) is not dict or set(payload) != {"args"} or type(payload["args"]) is not dict or payload["args"]:
            raise TypertGatewayError("arguments-invalid", "$events", "forwarded event stream requires empty args")
        registration = self.registration
        if registration is None:
            raise TypertGatewayError("service-unavailable", "$events", "forwarded event source unavailable")
        controller = AbortController()
        cleanups = [item.add_listener("abort", lambda *_: controller.abort()) for item in (signal, registration["controller"].signal)]
        client_id = str(uuid.uuid4())
        while client_id in self.clients:
            client_id = str(uuid.uuid4())
        client = {"id": client_id, "queue": EventQueue(), "deliveries": {}}
        self.clients[client_id] = client
        for pending in list(self.pending.values()):
            self.deliver(pending, client)
        try:
            yield {"type": "ready", "clientId": client_id, "host": registration["host"]}
            reader = cancellable_stream(client["queue"].iterate(), "$events", controller.signal)
            try:
                async for frame in reader:
                    yield frame
            except RemoteInvocationCancelled:
                if not controller.signal.aborted:
                    raise
            finally:
                await reader.aclose()
        finally:
            for cleanup in cleanups:
                cleanup()
            self.clients.pop(client_id, None)
            for pending in list(client["deliveries"].values()):
                self.remove_delivery(pending, client)
            client["queue"].end()

    @staticmethod
    def valid_name(value):
        if not isinstance(value.get("event"), str) or not value["event"]:
            raise ValueError("Remote event name must be a nonempty string")

    def broadcast(self, frame):
        self.valid_name(frame)
        if type(frame.get("args")) is not list:
            raise ValueError("Remote event args must be an array")
        lossless(frame["args"])
        wire = dict(type="emit", event=frame["event"], args=frame["args"])
        for client in self.clients.values():
            client["queue"].push(wire)

    def start(self, source):
        try:
            self.valid_name(source)
            context = self.ctx.get("typert").contexts.identifyHost(source["context"]["value"])
            if context is None:
                source["resolve"]({"kind": "next"})
                return
            if context["kind"] != "agent" or not isinstance(context["identity"], str) or not context["identity"]:
                raise ValueError("scoped Remote events require a nonempty Agent identity")
            request = source["request"]
            if type(request) is not dict or request.get("agent") is not source["context"]["subject"]:
                raise ValueError("Remote request must carry its scoped Agent directly")
            signal = request.get("signal")
            if signal is not None and not isinstance(signal, AbortSignal):
                raise ValueError("Remote event signal must be an AbortSignal")
            projected = {key: value for key, value in request.items() if key not in ("agent", "signal")}
            lossless(projected)
            event_id = str(uuid.uuid4())
            while event_id in self.pending:
                event_id = str(uuid.uuid4())
            pending = {"id": event_id, "source": source, "deliveries": {}, "release_signal": lambda: None,
                       "frame": {"type": "waterfall", "event": source["event"], "eventId": event_id,
                                 "agentId": context["identity"], "request": projected}}
            try:
                pending["release_context"] = source["context"]["value"].effect(
                    lambda: lambda: self.cancel(pending, RuntimeError("Remote event Context was released")), "Remote event context")
            except Exception:
                source["resolve"]({"kind": "next"})
                return
            self.pending[event_id] = pending
            if signal is not None:
                pending["release_signal"] = signal.add_listener("abort", lambda *_: self.cancel(pending, signal.reason if isinstance(signal.reason, Exception) else RuntimeError("Remote event cancelled")))
            if signal is None or not signal.aborted:
                for client in self.clients.values():
                    self.deliver(pending, client)
        except Exception as error:
            source["reject"](error)

    def deliver(self, pending, client):
        pending["deliveries"][client["id"]] = client
        client["deliveries"][pending["id"]] = pending
        client["queue"].push(pending["frame"])

    @staticmethod
    def remove_delivery(pending, client):
        pending["deliveries"].pop(client["id"], None)
        client["deliveries"].pop(pending["id"], None)

    def finish(self, pending):
        self.pending.pop(pending["id"], None)
        pending["release_signal"]()
        pending["release_context"]()
        for client in list(pending["deliveries"].values()):
            self.remove_delivery(pending, client)
            client["queue"].push({"type": "cancel", "eventId": pending["id"]})

    def cancel(self, pending, error):
        if self.pending.get(pending["id"]) is pending:
            self.finish(pending)
            pending["source"]["reject"](error)

    def result(self, payload):
        if type(payload) is not dict or set(payload) != {"args"}:
            raise ValueError("Remote event result requires exactly one args field")
        value = parse_result(payload["args"])
        client = self.clients.get(value["clientId"])
        if client is None:
            raise ValueError("Remote event result identifies no active event stream")
        pending = self.pending.get(value["eventId"])
        if pending is None or client["id"] not in pending["deliveries"]:
            return
        self.remove_delivery(pending, client)
        outcome = value["outcome"]
        if outcome["kind"] == "rejected":
            error = RuntimeError(outcome["error"]["message"])
            for key, item in outcome["error"].items():
                setattr(error, key, item)
            self.cancel(pending, error)
        elif outcome["kind"] == "result" or not pending["deliveries"]:
            self.finish(pending)
            pending["source"]["resolve"]({"kind": "result", "value": outcome.get("value", UNDEFINED)} if outcome["kind"] == "result" else {"kind": "next"})

    def close_events(self, reason):
        for pending in list(self.pending.values()):
            self.cancel(pending, reason)
        for client in self.clients.values():
            client["queue"].end()
