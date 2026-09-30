"""Workflow run seam and native orchestration host (Python 3.8 / Win7).

Deployment-owned programs may have a reviewed Python translation. This is not
a JavaScript interpreter: arbitrary script bodies fail before publishing a run.
"""

import asyncio
import inspect
import logging
import os
import uuid
from collections import deque

from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED
from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.tools import _assert_supported_schema, _json_snapshot
from dsh.llm.error import HarnessError
from .text import js_trim, utf16_length, utf16_slice

logger = logging.getLogger(__name__)
MAX_SAFE_INTEGER = 9007199254740991
DEFAULTS = dict(provider="spawn", maxConcurrentAgents=0, maxTotalAgents=1000,
                maxItemsPerCall=4096, syncTimeoutMs=5000, disposeGraceMs=5000)


class WorkflowError(HarnessError):
    def __init__(self, message, code, fatal=True):
        super().__init__(message, code)
        self.name, self.fatal = "WorkflowError", fatal


def safe_integer(value, minimum=1):
    return (type(value) in (int, float) and minimum <= value <= MAX_SAFE_INTEGER
            and int(value) == value)


def render_error(error):
    try:
        return error.message if isinstance(error, HarnessError) else str(error)
    except Exception:
        return "[unrenderable thrown value]"


def validate_meta(value):
    try:
        meta = _json_snapshot(value)
    except TypeError as error:
        raise WorkflowError("invalid meta: meta must be plain JSON data", "META_INVALID") from error
    if type(meta) is not dict:
        raise WorkflowError("invalid meta: meta must be an object", "META_INVALID")
    violations = []
    for key in meta:
        if key not in ("name", "description", "whenToUse", "phases"):
            violations.append("meta.{} is not a recognized field (name/description/whenToUse/phases)".format(key))
    for key in ("name", "description"):
        if type(meta.get(key)) is not str or not meta[key]:
            violations.append("meta.{} must be a non-empty string".format(key))
    if "whenToUse" in meta and type(meta["whenToUse"]) is not str:
        violations.append("meta.whenToUse must be a string")
    if "phases" in meta:
        if type(meta["phases"]) is not list:
            violations.append("meta.phases must be an array")
        else:
            for index, phase in enumerate(meta["phases"]):
                prefix = "meta.phases[{}]".format(index)
                if type(phase) is not dict:
                    violations.append(prefix + " must be an object")
                    continue
                for key in phase:
                    if key not in ("title", "detail", "provider", "model"):
                        violations.append(prefix + "." + key + " is not a recognized field")
                if type(phase.get("title")) is not str or not phase["title"]:
                    violations.append(prefix + ".title must be a non-empty string")
                for key in ("detail", "provider", "model"):
                    if key in phase and type(phase[key]) is not str:
                        violations.append(prefix + "." + key + " must be a string")
    if violations:
        raise WorkflowError("invalid meta: " + "; ".join(violations), "META_INVALID")
    return meta


def emit_workflow(ctx, name, *args):
    for callback in ctx.events.dispatch("emit", [ctx, name, *args]):
        try:
            returned = callback(*args)
            if inspect.isawaitable(returned):
                async def settle(result):
                    try:
                        await result
                    except Exception:
                        logger.warning("%s listener rejected", name, exc_info=True)
                asyncio.ensure_future(settle(returned))
        except Exception:
            logger.warning("%s listener threw", name, exc_info=True)


class WorkflowResult:
    def __init__(self, value=None, stop_reason="completed", error=None, agents_started=0):
        self.value, self.stop_reason = value, stop_reason
        self.error, self.agents_started = error, agents_started

    def to_dict(self):
        result = dict(value=self.value, stopReason=self.stop_reason, agentsStarted=self.agents_started)
        if self.error is not None:
            result["error"] = self.error
        return result


class WorkflowEngine(Service):
    inject = ["subagents"]
    Config = Schema.object(dict(
        provider=Schema.string().default("spawn"),
        **{key: Schema.number().default(value) for key, value in DEFAULTS.items() if key != "provider"}))

    def __init__(self, ctx, config=None):
        self.config = dict(DEFAULTS, **(config or {}))
        for key in DEFAULTS:
            if key != "provider" and not safe_integer(self.config[key], 0 if key in ("maxConcurrentAgents", "disposeGraceMs") else 1):
                raise TypeError("workflow config {} must be a {}safe integer".format(key, "non-negative " if key in ("maxConcurrentAgents", "disposeGraceMs") else "positive "))
        if type(self.config["provider"]) is not str or not self.config["provider"] or self.config["provider"] != js_trim(self.config["provider"]):
            raise TypeError("workflow provider must be a non-empty normalized string")
        self._native_programs = {}
        self._active_runs = {}
        super().__init__(ctx, "workflowEngine")

    def register_native_program(self, script, program):
        """Experimental exact-source mapping for trusted, ported built-ins."""
        if type(script) is not str or not script or not callable(program):
            raise TypeError("native workflow registration requires a script and callable")
        def setup():
            if script in self._native_programs:
                raise ValueError("a native translation for this workflow is already registered")
            self._native_programs[script] = program
            def dispose():
                if self._native_programs.get(script) is program:
                    del self._native_programs[script]
            yield dispose
        return self.ctx.effect(setup, "workflowEngine.register_native_program()")

    def start(self, request):
        meta = validate_meta(request.get("meta"))
        script = request.get("script")
        if type(script) is not str:
            raise WorkflowError("workflow script must be a string", "SCRIPT_PARSE")
        program = self._native_programs.get(script)
        if program is None:
            raise WorkflowError("JavaScript workflow execution is not available in this Python host; no reviewed native translation is registered for this script", "SCRIPT_RUNTIME_UNAVAILABLE")
        subagents = self.ctx.get("subagents")
        route = request.get("subagentProvider", self.config["provider"])
        if type(route) is not str or not route or route != js_trim(route):
            raise WorkflowError("workflow subagentProvider must be a non-empty normalized string", "INVALID_ARGUMENT")
        if subagents.getProvider(route) is None:
            raise WorkflowError('no subagent provider registered for "{}"'.format(route), "AGENT_START")
        cap = request.get("maxTotalAgents", self.config["maxTotalAgents"])
        if not safe_integer(cap):
            raise WorkflowError("workflow maxTotalAgents must be a positive safe integer", "INVALID_ARGUMENT")
        if cap > self.config["maxTotalAgents"]:
            raise WorkflowError("workflow maxTotalAgents {} exceeds the engine ceiling {}".format(cap, self.config["maxTotalAgents"]), "INVALID_ARGUMENT")
        if request.get("parent") is None:
            raise WorkflowError("workflow requires a parent agent", "INVALID_ARGUMENT")
        try:
            args = _json_snapshot(request.get("args"))
        except TypeError as error:
            raise WorkflowError("workflow args must be plain JSON data", "INVALID_ARGUMENT") from error
        limits = dict(self.config, maxTotalAgents=int(cap))
        limits["maxConcurrentAgents"] = int(limits["maxConcurrentAgents"] or min(16, max(1, (os.cpu_count() or 1) - 2)))
        run = WorkflowRun(self.ctx, subagents, str(uuid.uuid4()), meta, request["parent"],
                          route, program, args, limits, request.get("signal"))
        self._active_runs[run.id] = run
        active = self._active_runs
        run.result.add_done_callback(lambda _: active.pop(run.id, None))
        emit_workflow(self.ctx, "workflow/start", run.info)
        return run

    async def run(self, script_code, meta=None, **kwargs):
        """Compatibility entry; it executes the same run, never fabricates success."""
        run = self.start(dict(kwargs, script=script_code, meta=meta))
        try:
            return await asyncio.shield(run.result)
        finally:
            await run.dispose()


class WorkflowRun:
    def __init__(self, ctx, subagents, run_id, meta, parent, route, program, args, limits, signal):
        self.id, self.meta = run_id, meta
        self.info = dict(id=run_id, meta=_json_snapshot(meta))
        self.ctx, self.subagents, self.parent, self.route = ctx, subagents, parent, route
        self.args, self.limits = args, limits
        self.result = asyncio.get_event_loop().create_future()
        self.controller = AbortController()
        self.started, self._host_started, self._slots, self._phase = 0, 0, 0, None
        self._waiters, self._children, self._live = deque(), {}, {}
        self._starts, self._hooks = set(), set()
        self._reason, self._terminal, self._disposal, self._timer = None, False, None, None
        self._detach = lambda: None
        self._driver = asyncio.create_task(self._drive(program))
        if signal is not None:
            if aborted(signal):
                self.cancel("workflow start signal already aborted")
            else:
                self._detach = subscribe_abort(signal, lambda *_: self.cancel("workflow signal aborted"))

    def _check(self):
        if self._reason is not None or self._terminal:
            raise WorkflowError("workflow run cancelled: " + ("workflow settled" if self._reason is None else self._reason), "CANCELLED")

    def _task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._hooks.add(task)
        def done(future):
            self._hooks.discard(future)
            if not future.cancelled():
                future.exception()
        task.add_done_callback(done)
        return task

    def phase(self, title):
        self._check()
        if type(title) is not str or not title:
            raise WorkflowError("phase() requires a non-empty title string", "INVALID_ARGUMENT")
        self._phase = title
        emit_workflow(self.ctx, "workflow/phase", self.info, title)

    def log(self, message):
        self._check()
        if type(message) is not str:
            raise WorkflowError("log() requires a message string", "INVALID_ARGUMENT")
        emit_workflow(self.ctx, "workflow/log", self.info, message)

    def agent(self, prompt, opts=_UNDEFINED):
        self._check()
        if type(prompt) is not str or not prompt:
            raise WorkflowError("agent() requires a non-empty prompt string", "INVALID_ARGUMENT")
        try:
            options = _json_snapshot({} if opts is _UNDEFINED else opts)
        except TypeError as error:
            raise WorkflowError("agent() options must be plain JSON data", "INVALID_ARGUMENT") from error
        if type(options) is not dict:
            raise WorkflowError("agent() options must be an object", "INVALID_ARGUMENT")
        for key, value in options.items():
            if key not in ("label", "phase", "schema", "provider", "model"):
                raise WorkflowError('agent() option "{}" is {} (supported: label, phase, schema, provider, model)'.format(key, "deferred and not supported by this engine" if key in ("effort", "isolation", "agentType") else "not recognized"), "UNSUPPORTED_OPTION")
            if key != "schema" and type(value) is not str:
                raise WorkflowError('agent() option "{}" must be a string'.format(key), "INVALID_ARGUMENT")
        if "schema" in options:
            try:
                _assert_supported_schema(options["schema"])
                if options["schema"].get("type") != "object":
                    raise TypeError("schema root must be an object")
            except TypeError as error:
                raise WorkflowError("agent() schema is outside the supported subset: " + str(error), "UNSUPPORTED_SCHEMA") from error
        if self.started >= self.limits["maxTotalAgents"]:
            raise WorkflowError("this run reached its total agent cap ({})".format(self.limits["maxTotalAgents"]), "AGENT_CAP")
        self.started += 1
        line = prompt.split("\n", 1)[0]
        label = options.get("label", line if utf16_length(line) <= 48 else utf16_slice(line, 47) + "\u2026")
        info = dict(seq=self.started, label=label)
        phase = options.get("phase", self._phase)
        if phase is not None:
            info["phase"] = phase
        return self._task(self._agent(prompt, options, info))

    async def _acquire(self):
        if self._slots < self.limits["maxConcurrentAgents"]:
            self._slots += 1
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                self._release()
                raise
        else:
            waiter = asyncio.get_event_loop().create_future()
            self._waiters.append(waiter)
            try:
                await waiter
            except asyncio.CancelledError:
                if not waiter.cancelled() and waiter.exception() is None:
                    self._release()
                raise

    def _release(self):
        self._slots -= 1
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                self._slots += 1
                waiter.set_result(None)
                break

    async def _start_child(self, request, seq):
        self._host_started += 1
        run = await self.subagents.start(self.route, request)
        record = dict(run=run, disposal=None)
        if self._reason is not None or self._terminal:
            await self._dispose_child(seq, record)
            self._check()
        self._children[seq] = record
        return record

    def _dispose_child(self, seq, record):
        if record["disposal"] is None:
            async def dispose():
                try:
                    await record["run"].dispose()
                except Exception:
                    logger.warning("workflow child dispose failed", exc_info=True)
                finally:
                    if self._children.get(seq) is record:
                        del self._children[seq]
            record["disposal"] = asyncio.create_task(dispose())
        return record["disposal"]

    async def _agent(self, prompt, opts, info):
        acquired = False
        try:
            await self._acquire()
            acquired = True
            self._check()
            request = dict(prompt=[dict(type="text", text=prompt)], parent=self.parent, signal=self.controller.signal)
            if "schema" in opts:
                request["outputSchema"] = opts["schema"]
            overrides = {key: opts[key] for key in ("provider", "model") if key in opts}
            if overrides:
                request["agentOptions"] = overrides
            start = asyncio.create_task(self._start_child(request, info["seq"]))
            self._starts.add(start)
            def started(future):
                self._starts.discard(future)
                if not future.cancelled():
                    future.exception()
            start.add_done_callback(started)
            try:
                record = await asyncio.shield(start)
            except Exception as error:
                self._check()
                raise WorkflowError("agent() could not start a child: " + render_error(error), "AGENT_START") from error
            run = record["run"]
            info = dict(info, childId=run.id)
            self._live[info["seq"]] = info
            emit_workflow(self.ctx, "workflow/agent-start", self.info, info)
            try:
                try:
                    result = _json_snapshot(await asyncio.shield(run.result))
                except Exception as error:
                    self._end_agent(info, "cancelled" if self._reason is not None else "failed")
                    self._check()
                    raise WorkflowError("child agent run failed: " + render_error(error), "AGENT_RESULT") from error
                if result["stopReason"] == "completed":
                    if "schema" in opts:
                        if "structured" not in result:
                            self._end_agent(info, "failed")
                            return None
                        value = result["structured"]
                    else:
                        value = "".join(block["text"] for block in result["output"] if block["type"] == "text")
                    self._end_agent(info, "completed")
                    return value
                if self._reason is not None:
                    self._end_agent(info, "cancelled")
                    self._check()
                self._end_agent(info, "failed")
                return None
            finally:
                await asyncio.shield(self._dispose_child(info["seq"], record))
        finally:
            if acquired:
                self._release()

    def _end_agent(self, info, outcome):
        if self._live.pop(info["seq"], None) is not None:
            emit_workflow(self.ctx, "workflow/agent-end", self.info, dict(info, outcome=outcome))

    def _items(self, items, hook):
        self._check()
        if type(items) is not list:
            raise WorkflowError(hook + " requires an array", "INVALID_ARGUMENT")
        if len(items) > self.limits["maxItemsPerCall"]:
            raise WorkflowError("{} received {} items over the per-call cap ({})".format(hook, len(items), self.limits["maxItemsPerCall"]), "ITEM_CAP")

    async def _invoke(self, callback, *args):
        result = callback(*args)
        return await result if inspect.isawaitable(result) else result

    def parallel(self, thunks):
        self._items(thunks, "parallel()")
        if any(not callable(thunk) for thunk in thunks):
            raise WorkflowError("parallel() requires function items", "INVALID_ARGUMENT")
        async def one(thunk):
            try:
                return await self._invoke(thunk)
            except Exception as error:
                if isinstance(error, WorkflowError) and error.fatal:
                    raise
                return None
        async def drive():
            return await asyncio.gather(*(self._task(one(thunk)) for thunk in thunks))
        return self._task(drive())

    def pipeline(self, items, *stages):
        self._items(items, "pipeline()")
        if not stages or any(not callable(stage) for stage in stages):
            raise WorkflowError("pipeline() requires at least one stage function and only function stages", "INVALID_ARGUMENT")
        async def one(item, index):
            value = item
            try:
                for stage in stages:
                    value = await self._invoke(stage, value, item, index)
                return value
            except Exception as error:
                if isinstance(error, WorkflowError) and error.fatal:
                    raise
                return None
        async def drive():
            return await asyncio.gather(*(self._task(one(item, index)) for index, item in enumerate(items)))
        return self._task(drive())

    async def _drive(self, program):
        try:
            self._check()
            value = await self._invoke(program, self)
            self._check()
            try:
                value = _json_snapshot(value)
            except TypeError as error:
                raise WorkflowError("the workflow's return value is not plain JSON data", "RESULT_UNSERIALIZABLE") from error
            result = WorkflowResult(value=value, agents_started=self.started).to_dict()
        except asyncio.CancelledError:
            result = self._cancelled_result()
        except Exception as error:
            result = self._cancelled_result() if self._reason is not None else WorkflowResult(stop_reason="error", error=render_error(error), agents_started=self.started).to_dict()
        self._settle(result)

    def _cancelled_result(self, forced=False):
        return WorkflowResult(stop_reason="cancelled", error="workflow run cancelled: " + ("workflow disposed" if self._reason is None else self._reason),
                              agents_started=self._host_started if forced else self.started).to_dict()

    def _reap(self):
        self.controller.abort("workflow settled" if self._reason is None else self._reason)
        for seq, record in list(self._children.items()):
            self._dispose_child(seq, record)

    def _settle(self, result):
        if self._terminal:
            return
        self._terminal = True
        if self._timer is not None:
            self._timer.cancel()
        self._detach()
        # Claim the outcome before cleanup callbacks can reenter cancel().
        self._reap()
        for info in list(self._live.values()):
            self._end_agent(info, "cancelled")
        for task in list(self._hooks):
            task.cancel()
        self.result.set_result(result)
        outcome = {key: value for key, value in result.items() if key != "value"}
        emit_workflow(self.ctx, "workflow/end", self.info, outcome)

    def cancel(self, reason=None):
        if self._terminal or self._reason is not None:
            return
        self._reason = "workflow cancelled" if reason is None else reason
        self.controller.abort(self._reason)
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_exception(WorkflowError("workflow run cancelled: " + self._reason, "CANCELLED"))
        def force():
            self._settle(self._cancelled_result(forced=True))
            self._driver.cancel()
        self._timer = asyncio.get_event_loop().call_later(self.limits["disposeGraceMs"] / 1000, force)

    def dispose(self):
        if self._disposal is None:
            # Claim before abort/dispose callbacks can reenter this method.
            self._disposal = asyncio.get_event_loop().create_future()
            self._detach()
            self.cancel("workflow disposed")
            self._reap()
            async def dispose():
                async def quiesce():
                    await asyncio.shield(self.result)
                    while self._children or self._starts:
                        pending = list(self._starts) + [record["disposal"] for record in self._children.values() if record["disposal"] is not None]
                        if pending:
                            await asyncio.gather(*(asyncio.shield(task) for task in pending), return_exceptions=True)
                        else:
                            await asyncio.sleep(0)
                wait = asyncio.create_task(quiesce())
                try:
                    await asyncio.wait_for(asyncio.shield(wait), self.limits["disposeGraceMs"] / 1000)
                except asyncio.TimeoutError:
                    wait.cancel()
                    self._settle(self._cancelled_result(forced=True))
                finally:
                    self._driver.cancel()
                    self._reap()
            task = asyncio.create_task(dispose())
            def settled(future):
                if future.cancelled():
                    self._disposal.cancel()
                elif future.exception() is not None:
                    self._disposal.set_exception(future.exception())
                else:
                    self._disposal.set_result(None)
            task.add_done_callback(settled)
        return asyncio.shield(self._disposal)
