"""Process-local jobs with exact lifecycle owners and scoped controllers."""
import asyncio
import copy
import inspect
import logging
import math
import time

from dsh.cordis.service import Service
from dsh.core.cancellation import aborted
from dsh.core.scope import AnonymousEntries, ScopedLayers, scope_of


def terminal(job):
    return job["status"] in ("completed", "killed", "failed")


def member(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


class JobLayer:
    def __init__(self):
        self.controllers, self.listeners, self.changed = AnonymousEntries(), AnonymousEntries(), AnonymousEntries()

    def is_empty(self):
        return all(table.is_empty() for table in (self.controllers, self.listeners, self.changed))


class LocalJobRegistry(Service):
    def __init__(self, ctx, config=None):
        config = config or {}
        maximum = config.get("maxConcurrentJobsPerOwner", 10)
        if type(maximum) is not int or not 1 <= maximum <= 9007199254740991:
            raise ValueError("maxConcurrentJobsPerOwner must be a positive safe integer")
        super().__init__(ctx, "jobs")
        self.maximum = maximum
        self.store, self.counters, self.owner_cleanups = {}, {}, {}
        self.layers = ScopedLayers(lambda _: JobLayer())
        self.lifetime = {"closed": False}
        self.self_ctx = ctx
        self.tasks = set()
        ctx.effect(lambda: self.close, "jobs teardown")

    def _layers_for(self, owner):
        return [self.layers.global_layer] + self.layers.chain_layers(scope_of(owner.ctx) if owner is not None else None)

    def _register(self, field, value):
        return self.layers.effect(self.ctx, lambda layer: getattr(layer, field).append(value), {"label": "jobs." + field})

    def attach_controller(self, name):
        return self._register("controllers", object())

    attachController = attach_controller

    def on_job_done(self, listener):
        return self._register("listeners", listener)

    onJobDone = on_job_done

    def on_jobs_changed(self, listener):
        return self._register("changed", listener)

    onJobsChanged = on_jobs_changed

    def _announce(self, field, owner, *args):
        for layer in self._layers_for(owner):
            for listener in getattr(layer, field).values():
                try:
                    result = listener(*(copy.deepcopy(arg) if isinstance(arg, dict) else arg for arg in args))
                    if inspect.isawaitable(result):
                        async def contain(pending):
                            try:
                                await pending
                            except Exception as error:
                                logging.getLogger("jobs").warning("Listener failed: %s", error)
                        asyncio.create_task(contain(result))
                except Exception as error:
                    logging.getLogger("jobs").warning("Listener failed: %s", error)

    def _changed(self, owner):
        self._announce("changed", owner, owner)

    def _own(self, owner):
        if owner is None:
            return
        agents = self.self_ctx.get("agents")
        if agents is None or agents.get(owner.id) is not owner:
            raise ValueError("background job owner must be the live registered Agent")
        if owner not in self.owner_cleanups:
            async def close_owner():
                self.owner_cleanups.pop(owner, None)
                jobs = [j for j in self.store.values() if j["owner"] is owner]
                await self._retire(jobs, "owner disposed")
                for job in jobs:
                    self.store.pop(job["id"], None)
                if jobs:
                    self._changed(owner)
            self.owner_cleanups[owner] = owner.ctx.effect(lambda: close_owner, "jobs.ownerCleanup()")

    def start(self, spec):
        owner = spec.get("owner")
        if self.lifetime["closed"]:
            raise RuntimeError("jobs service disposed")
        if not any(not layer.controllers.is_empty() for layer in self._layers_for(owner)):
            raise ValueError("background jobs unavailable: no job controller serves this agent")
        for field in ("kind", "label"):
            if not isinstance(spec.get(field), str) or not spec[field]:
                raise ValueError("invalid job " + field)
        limit = spec.get("outputLimitBytes")
        if limit is not None and (type(limit) is not int or not 0 < limit <= 9007199254740991):
            raise ValueError("invalid outputLimitBytes")
        self._own(owner)
        if sum(j["owner"] is owner and not terminal(j) for j in self.store.values()) >= self.maximum:
            raise ValueError("background job limit reached for this owner")
        hooks = spec["run"]()
        number = self.counters.get(spec["kind"], 0) + 1
        self.counters[spec["kind"]] = number
        job_id = "{}-{}".format(spec["kind"], number)
        job = dict(id=job_id, kind=spec["kind"], label=spec["label"], owner=owner, outputLimitBytes=limit,
                   status="running", reported=False, startedAt=int(time.time() * 1000), waiters={},
                   settled=asyncio.Event(), cancel=member(hooks, "cancel"), readOutput=member(hooks, "readOutput"))
        self.store[job_id] = job

        async def finish():
            try:
                outcome = await member(hooks, "done")
                if not isinstance(outcome, dict) or outcome.get("status") not in ("completed", "killed", "failed"):
                    raise ValueError("invalid producer outcome")
            except asyncio.CancelledError:
                outcome = {"status": "killed"}
            except Exception as error:
                logging.getLogger("jobs").warning("Producer done rejected: %s", error)
                outcome = {"status": "failed", "detail": str(error)}
            self._settle(job, outcome)
        task = asyncio.create_task(finish())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        self._changed(owner)
        return job_id

    def _expect(self, job_id, caller):
        if job_id not in self.store:
            raise ValueError("unknown job " + job_id)
        job = self.store[job_id]
        if job["owner"] is not None and job["owner"].id != getattr(caller, "id", None):
            raise ValueError("job belongs to another session")
        return job

    def _snapshot(self, job):
        value = {key: copy.deepcopy(job[key]) for key in
                 ("id", "kind", "label", "status", "detail", "outputLimitBytes", "startedAt", "finishedAt", "reported")
                 if job.get(key) is not None}
        if job["owner"] is not None:
            value["ownerSession"] = job["owner"].id
        return value

    def list(self, caller=None):
        return [self._snapshot(j) for j in self.store.values()
                if j["owner"] is None or j["owner"].id == getattr(caller, "id", None)]

    def get(self, job_id, caller=None):
        return self._snapshot(self._expect(job_id, caller))

    def read(self, job_id, caller=None):
        job = self._expect(job_id, caller)
        text = job["readOutput"]() if job["readOutput"] is not None else job.get("output", "") if terminal(job) else ""
        if terminal(job):
            job["reported"] = True
        return {"text": text, "snapshot": self._snapshot(job)}

    def kill(self, job_id, caller=None, reason=None):
        job = self._expect(job_id, caller)
        if terminal(job):
            job["reported"] = True
            return "already-finished"
        job["cancel"](reason)
        job.update(status="stopping", reported=True)
        self._changed(job["owner"])
        return "requested"

    async def wait(self, job_id, timeout_ms, caller=None, signal=None):
        job = self._expect(job_id, caller)
        if type(timeout_ms) not in (float, int) or not math.isfinite(timeout_ms) or timeout_ms <= 0:
            raise ValueError("invalid wait timeout")
        if not terminal(job):
            if aborted(signal):
                raise RuntimeError("wait aborted")
            loop = asyncio.get_running_loop()
            token, result = object(), loop.create_future()
            remove, poll = [None], [None]

            def detach():
                job["waiters"].pop(token, None)
                if remove[0] is not None:
                    remove[0]()
                    remove[0] = None
                if poll[0] is not None:
                    poll[0].cancel()
                    poll[0] = None

            def finish(error=None):
                if result.done():
                    return
                detach()
                if error is None:
                    result.set_result(None)
                else:
                    result.set_exception(error)

            def on_abort(*_):
                finish(RuntimeError("wait aborted"))

            def check():
                if aborted(signal):
                    on_abort()
                elif not result.done():
                    poll[0] = loop.call_later(0.02, check)

            job["waiters"][token] = finish
            if callable(getattr(signal, "add_listener", None)):
                remove[0] = signal.add_listener("abort", on_abort)
            elif signal is not None:
                poll[0] = loop.call_later(0.02, check)
            timer = loop.call_later(timeout_ms / 1000, finish)
            try:
                await result
            finally:
                timer.cancel()
                detach()

        if terminal(job):
            job["reported"] = True
        return self._snapshot(job)

    def _settle(self, job, outcome):
        if terminal(job):
            return
        job.update({k: outcome[k] for k in ("status", "detail", "output") if k in outcome})
        job["finishedAt"] = int(time.time() * 1000)
        if job["waiters"]:
            job["reported"] = True
        for finish in list(job["waiters"].values()):
            finish()
        snapshot = self._snapshot(job)
        job["settled"].set()
        self._changed(job["owner"])
        if not self.lifetime["closed"]:
            self._announce("listeners", job["owner"], snapshot, job["owner"])

    async def _retire(self, jobs, reason):
        for job in jobs:
            if terminal(job):
                continue
            job["reported"] = True
            try:
                job["cancel"](reason)
                job["status"] = "stopping"
                self._changed(job["owner"])
            except Exception as error:
                detail = "cancel threw during teardown; work may be orphaned: " + str(error)
                logging.getLogger("jobs").warning(detail)
                self._settle(job, {"status": "failed", "detail": detail})
        await asyncio.gather(*(job["settled"].wait() for job in jobs))

    async def close(self):
        self.lifetime["closed"] = True
        jobs = list(self.store.values())
        await self._retire(jobs, "jobs service disposed")
        self.store.clear()
        for owner in {j["owner"] for j in jobs}:
            self._changed(owner)
        cleanups = list(self.owner_cleanups.values())
        self.owner_cleanups.clear()
        for cleanup in cleanups:
            result = cleanup()
            if inspect.isawaitable(result):
                await result
