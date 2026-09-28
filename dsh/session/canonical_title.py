"""Log-owned titles with revision-safe optional asynchronous generation."""
import asyncio
import copy
import inspect
import logging

from dsh.cordis.service import Service
from dsh.cordis.fiber import FiberState
from dsh.core.abort import AbortController
from dsh.llm.agent_request import is_agent_loop_request
from dsh.session.title import collect_session_title_messages, fold_session_title, fallback_session_title, normalize_session_title


def title_schema(value):
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError("title projection must be null or non-empty string")
    return value


class SessionTitleService(Service):
    inject = ["sessions"]

    def __init__(self, ctx, config):
        for key in ("fallbackMaxWords", "fallbackMaxBytes", "maxTitleBytes"):
            if type(config.get(key)) is not int or config[key] < 1:
                raise ValueError("session-title: " + key + " must be a positive integer")
        if config["fallbackMaxBytes"] > config["maxTitleBytes"]:
            raise ValueError("fallbackMaxBytes must not exceed maxTitleBytes")
        super().__init__(ctx, "sessionTitle")
        self.config, self.owner = dict(config), ctx
        self.registration, self.work, self.tasks = None, {}, set()
        self.closed = False
        ctx.effect(lambda: self.close, "session title lifecycle")
        def projection(child):
            child.get("sessionProjections").register({"key": "title", "stateVersion": 1,
                "stateSchema": title_schema, "init": lambda _: None,
                "apply": lambda state, event: event["data"]["title"] if event["type"] == "session/title" else state,
                "wire": {"viewSchema": title_schema, "view": lambda state: state}})
        ctx.inject(["sessionProjections"], projection)
        ctx.on("session/event", self._event)
        ctx.on("session/disposed", self._disposed)
        ctx.on("llm/stream", self._main_request, {"global": True, "prepend": True})

    def _active(self):
        return not self.closed and self.owner.fiber.uid is not None and self.owner.fiber.state == FiberState.ACTIVE

    def _live(self, session):
        if not self._active():
            raise RuntimeError("session-title service disposed")
        if self.owner.get("sessions").get(session.id) is not session:
            raise RuntimeError("session is not live in this store")

    def get(self, session):
        return copy.deepcopy(fold_session_title(session.events))

    def get_title(self, session):
        current = self.get(session)
        return current["title"] if current else "Untitled Session"

    def _state(self, session):
        if session not in self.work:
            self.work[session] = {"revision": 0}
        return self.work[session]

    def _supersede(self, state, reason):
        if state.get("active"):
            state["active"]["controller"].abort(reason)
        state.pop("pending", None)
        state["revision"] += 1
        return state["revision"]

    def rename(self, session, title):
        self._live(session)
        value = normalize_session_title(title, self.config["maxTitleBytes"])
        if not value:
            raise ValueError("session title must contain visible characters")
        self._supersede(self._state(session), "user rename")
        session.append("session/title", {"title": value, "messageSeqs": [], "source": {"kind": "user"}})
        return self.get(session)

    set_title = rename

    def _append_fallback(self, session, first):
        title = fallback_session_title(first["text"], self.config["fallbackMaxWords"], self.config["fallbackMaxBytes"])
        if title:
            session.append("session/title", {"title": title, "messageSeqs": [first["seq"]], "source": {"kind": "fallback"}})

    async def _fallback(self, session):
        self._live(session)
        if self.get(session) is None:
            messages = collect_session_title_messages(session.events)
            if messages:
                self._append_fallback(session, messages[0])
        return self.get(session)

    def _track(self, coro, registration=None):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        if registration:
            registration["tasks"].add(task)
        def done(future):
            self.tasks.discard(future)
            if registration:
                registration["tasks"].discard(future)
            if not future.cancelled():
                future.exception()
        task.add_done_callback(done)
        return task

    async def _drain(self, tasks):
        while tasks:
            await asyncio.gather(*list(tasks), return_exceptions=True)

    def register(self, provider):
        if not isinstance(provider, dict) or not isinstance(provider.get("id"), str) or not provider["id"]:
            raise ValueError("session-title provider requires a non-empty id")
        if provider.get("automatic") not in ("first-prompt", "all-prompts") or not callable(provider.get("generate")):
            raise ValueError("session-title provider requires automatic cadence and generate")
        if self.registration is not None:
            raise ValueError("session-title provider is already registered")
        registration = {"provider": provider, "closing": False, "tasks": set()}
        def setup():
            self.registration = registration
            async def cleanup():
                registration["closing"] = True
                for state in list(self.work.values()):
                    if state.get("pending", {}).get("registration") is registration:
                        state.pop("pending", None)
                    if state.get("active", {}).get("registration") is registration:
                        state["active"]["controller"].abort("title provider disposed")
                await self._drain(registration["tasks"])
                if self.registration is registration:
                    self.registration = None
            return cleanup
        return self.ctx.effect(setup, "sessionTitle.register()")

    def _activate(self, state, pending, signal=None):
        controller = AbortController()
        cleanup = signal.add_listener("abort", lambda *_: controller.abort("caller aborted")) if signal is not None else lambda: None
        work = dict(pending, controller=controller, signal=controller.signal, cleanup=cleanup)
        state["active"] = work
        return work

    def _current(self, session, work):
        self._live(session)
        work["signal"].throw_if_aborted()
        state = self.work.get(session, {})
        if self.registration is not work["registration"] or state.get("active") is not work or state["revision"] != work["revision"]:
            raise RuntimeError("session title generation state changed")

    def _validate_result(self, result, messages):
        if not isinstance(result, dict) or not isinstance(result.get("title"), str):
            raise ValueError("invalid title provider result")
        title = normalize_session_title(result["title"], self.config["maxTitleBytes"])
        seqs = result.get("messageSeqs")
        if not title or not isinstance(seqs, list) or not seqs:
            raise ValueError("title provider requires visible text and messageSeqs")
        order, previous = {row["seq"]: i for i, row in enumerate(messages)}, -1
        for seq in seqs:
            if type(seq) is not int or seq < 0 or seq > 9007199254740991 or seq not in order or order[seq] <= previous:
                raise ValueError("title source seqs must be unique ordered request seqs")
            previous = order[seq]
        model = result.get("model")
        if model is not None and (not isinstance(model, dict) or any(not isinstance(model.get(key), str) or not model[key] for key in ("provider", "model"))):
            raise ValueError("title model requires provider and model strings")
        return title, seqs, model

    async def _run(self, session, work, route):
        try:
            self._current(session, work)
            await self._fallback(session)
            self._current(session, work)
            messages = collect_session_title_messages(session.events, work["throughSeq"])
            request = {"session": session, "messages": messages, "signal": work["signal"]}
            if route is not None:
                request["route"] = route
            result = work["registration"]["provider"]["generate"](request)
            if inspect.isawaitable(result):
                result = await result
            self._current(session, work)
            title, seqs, model = self._validate_result(result, messages)
            source = {"kind": "provider", "provider": work["registration"]["provider"]["id"]}
            if model is not None:
                source["model"] = model
            session.append("session/title", {"title": title, "messageSeqs": seqs, "source": source})
            return self.get(session)
        finally:
            work["cleanup"]()
            state = self.work.get(session)
            if state and state.get("active") is work:
                state.pop("active", None)

    async def refresh(self, session, signal=None):
        if signal is not None:
            signal.throw_if_aborted()
        self._live(session)
        messages, registration = collect_session_title_messages(session.events), self.registration
        if not messages or registration is None or registration["closing"]:
            current = self.get(session)
            if current and current["source"]["kind"] == "user" and messages:
                self._append_fallback(session, messages[0])
            result = await self._fallback(session)
            if signal is not None:
                signal.throw_if_aborted()
            return result
        state = self._state(session)
        pending = {"registration": registration, "revision": self._supersede(state, "explicit title refresh"), "throughSeq": messages[-1]["seq"]}
        work = self._activate(state, pending, signal)
        route = (session.request_header() or {}).get("config")
        route = {key: route[key] for key in ("provider", "model")} if route else None
        return await self._track(self._run(session, work, route), registration)

    def _start_pending(self, session, state, pending, route):
        state.pop("pending", None)
        async def start():
            if self.registration is not pending["registration"] or pending["registration"]["closing"] or self.work.get(session) is not state or state["revision"] != pending["revision"] or not self._active():
                return
            work = self._activate(state, pending)
            try:
                await self._run(session, work, route)
            except Exception as error:
                if not work["signal"].aborted and self._active():
                    logging.getLogger("session-title").warning("Automatic title failed: %s", error)
        self._track(start(), pending["registration"])

    def _event(self, session, event):
        if not self._active():
            return
        if event["type"] == "user/message":
            if not collect_session_title_messages([event]) or (self.get(session) or {}).get("source", {}).get("kind") == "user":
                return
            registration = self.registration
            if registration is not None and not registration["closing"]:
                messages = collect_session_title_messages(session.events, event["seq"])
                if registration["provider"]["automatic"] == "all-prompts" or (not session.header.parentSession and len(messages) == 1 and self.get(session) is None):
                    state = self._state(session)
                    state["pending"] = {"registration": registration, "revision": self._supersede(state, "new user message"), "throughSeq": event["seq"]}
            async def fallback():
                try:
                    if self._active():
                        await self._fallback(session)
                except Exception as error:
                    if self._active():
                        logging.getLogger("session-title").warning("Fallback title failed: %s", error)
            self._track(fallback())
        elif event["type"] == "request/header":
            state = self.work.get(session)
            pending = state.get("pending") if state else None
            if pending is not None and pending["throughSeq"] < event["seq"]:
                config = event["data"]["header"]["config"]
                self._start_pending(session, state, pending, {key: config[key] for key in ("provider", "model")})

    async def _main_request(self, options, next_fn):
        if self._active() and is_agent_loop_request(options):
            session = self.owner.get("sessions").get(options.get("sessionId"))
            state = self.work.get(session)
            pending = state.get("pending") if state else None
            if pending is not None:
                boundary = next((event for event in reversed(session.events) if event["type"] in ("step/start", "step/end")), None)
                route = (session.request_header() or {}).get("config", {})
                if boundary and boundary["type"] == "step/start" and boundary["seq"] > pending["throughSeq"] and all(route.get(key) == options.get(key) for key in ("provider", "model")):
                    self._start_pending(session, state, pending, {key: route[key] for key in ("provider", "model")})
        return await next_fn()

    def _disposed(self, session):
        state = self.work.pop(session, None)
        if state and state.get("active"):
            state["active"]["controller"].abort("session disposed")

    async def close(self):
        self.closed = True
        if self.registration is not None:
            self.registration["closing"] = True
        self.registration = None
        for state in list(self.work.values()):
            self._supersede(state, "session title service disposed")
        await self._drain(self.tasks)
        self.work.clear()
