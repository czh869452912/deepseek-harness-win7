"""Log-owned goals with CAS mutations and process-local continuation authority."""
import copy
import re
import time
import uuid
import weakref

from dsh.typert.remote import TypertRemoteService, Remote
from dsh.core.notifications import emit_contained
from dsh.llm.error import HarnessError
from dsh.goal.fold import (integer, empty_goal_state, apply_goal_event, goal_ref,
                           apply_goal_projection, projection_schema)


class GoalError(HarnessError, ValueError):
    def __init__(self, message, code):
        super().__init__(message, code)

    def __str__(self):
        return self.message


def max_rounds(value):
    try:
        return integer(value, 1)
    except ValueError:
        raise GoalError("maxGoalRounds must be a positive safe integer", "GOAL_INVALID_MAX_ROUNDS")


def objective(value):
    if not isinstance(value, str) or not value.strip():
        raise GoalError("goal objective must be a non-empty string", "GOAL_INVALID_OBJECTIVE")
    return value.strip()


class GoalService(TypertRemoteService):
    inject = ["agents"]

    def __init__(self, ctx, config=None):
        self.default_rounds = max_rounds((config or {}).get("defaultMaxGoalRounds", 256))
        super().__init__(ctx, "goals")
        self.caches = weakref.WeakKeyDictionary()
        ctx.on("agent/session-start", self._session_start)
        def projection(child):
            child.get("sessionProjections").register({"key": "goal", "stateVersion": 4,
                "stateSchema": projection_schema, "init": lambda _: None, "apply": apply_goal_projection,
                "wire": {"viewSchema": projection_schema, "view": lambda state: state}})
        ctx.inject(["sessionProjections"], projection)

    def _session_start(self, payload):
        self._cache(payload["agent"].session)["activation"] = "disarmed"

    def _cache(self, session):
        if session not in self.caches:
            state = empty_goal_state()
            for event in session.events:
                apply_goal_event(state, event)
            self.caches[session] = {"state": state, "activation": "disarmed", "observed": session.seq, "pending": None}
        return self.caches[session]

    def _sync(self, session, cache):
        for event in session.events[cache["observed"]:]:
            apply_goal_event(cache["state"], event)
            if event["type"] == "goal/change":
                pending = cache["pending"]
                cache["activation"] = pending[1] if pending is not None and pending[0] == event["seq"] else "disarmed"
            cache["observed"] += 1

    def _prepare(self, agent):
        if self.ctx.get("agents").get(agent.id) is not agent:
            raise GoalError('agent "{}" is not live in this registry'.format(agent.id), "GOAL_AGENT_NOT_LIVE")
        cache = self._cache(agent.session)
        self._sync(agent.session, cache)
        return cache

    def _view(self, cache):
        state = cache["state"]
        if state["goal"] is None:
            return None
        return dict(copy.deepcopy(state["goal"]), activation=cache["activation"],
                    **{key: state[key] for key in ("roundsStarted", "createdAt", "updatedAt")})

    def get(self, agent):
        return self._view(self._prepare(agent))

    def disarm(self, agent):
        cache = self._prepare(agent)
        cache["activation"] = "disarmed"
        return self._view(cache)

    def _expect(self, cache, ref):
        current = cache["state"]["goal"]
        if current is None:
            raise GoalError("no current goal", "GOAL_NOT_FOUND")
        if not isinstance(ref, dict) or ref.get("id") != current["id"] or ref.get("revision") != current["revision"]:
            raise GoalError("stale goal ref", "GOAL_STALE_REVISION")
        return current

    def _commit(self, agent, cache, change, activation):
        ref = copy.deepcopy(change.get("cleared") or goal_ref(change["goal"]))
        cache["pending"] = (agent.session.seq, activation)
        try:
            agent.session.append("goal/change", change)
            self._sync(agent.session, cache)
        finally:
            cache["pending"] = None
        view = self._view(cache)
        notification = {"operation": change["operation"], "ref": ref}
        if view is not None:
            notification["goal"] = view
        emit_contained(self.ctx, "goal/changed", {"agent": agent, "change": notification}, agent)
        return view

    def _snapshot(self, agent, cache, operation, goal, activation, new=False):
        state, now = cache["state"], int(time.time() * 1000)
        return self._commit(agent, cache, {"kind": "goal/change", "version": 1, "operation": operation,
            "goal": goal, "roundsStarted": 0 if new else state["roundsStarted"],
            "createdAt": now if new else state["createdAt"],
            "updatedAt": now if new else max(now, state["updatedAt"])}, activation)

    def create(self, agent, request):
        text = objective(request.get("objective"))
        rounds = max_rounds(request.get("maxGoalRounds", self.default_rounds))
        cache = self._prepare(agent)
        current = cache["state"]["goal"]
        if current is not None and current["phase"] != "complete":
            raise GoalError("goal already exists", "GOAL_ALREADY_EXISTS")
        return self._snapshot(agent, cache, "create", {"id": "goal-" + str(uuid.uuid4()), "revision": 1,
            "objective": text, "phase": "active", "maxGoalRounds": rounds}, "armed", new=True)

    @Remote("create")
    def remote_export_create(self, agent, request):
        return {"ref": goal_ref(self.create(agent, request))}

    @Remote("edit")
    def edit(self, agent, ref, request):
        cache = self._prepare(agent)
        current = self._expect(cache, ref)
        if not any(key in request for key in ("objective", "maxGoalRounds")):
            raise GoalError("goal edit requires objective or maxGoalRounds", "GOAL_INVALID_EDIT")
        goal = copy.deepcopy(current)
        goal["revision"] += 1
        if "objective" in request:
            goal["objective"] = objective(request["objective"])
        if "maxGoalRounds" in request:
            goal["maxGoalRounds"] = max_rounds(request["maxGoalRounds"])
        return self._snapshot(agent, cache, "edit", goal, cache["activation"])

    def _transition(self, agent, ref, operation, allowed, phase, activation, reason=None):
        cache = self._prepare(agent)
        current = self._expect(cache, ref)
        if (current["phase"] not in allowed or (operation == "resume" and
                ((current["phase"] == "active" and cache["activation"] == "armed")
                 or cache["state"]["roundsStarted"] >= current["maxGoalRounds"]))):
            raise GoalError("cannot {} goal from current state".format(operation), "GOAL_INVALID_TRANSITION")
        goal = dict(current, revision=current["revision"] + 1, phase=phase)
        goal.pop("blockedReason", None)
        if reason is not None:
            code, message = reason.get("code"), reason.get("message")
            if (not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", code) is None
                    or not isinstance(message, str) or not message.strip()):
                raise GoalError("invalid goal block reason", "GOAL_INVALID_BLOCK_REASON")
            goal["blockedReason"] = {"code": code, "message": message.strip()}
        return self._snapshot(agent, cache, operation, goal, activation)

    @Remote("pause")
    def pause(self, agent, ref):
        return self._transition(agent, ref, "pause", ("active",), "paused", "disarmed")

    @Remote("resume")
    def resume(self, agent, ref):
        return self._transition(agent, ref, "resume", ("active", "paused", "blocked"), "active", "armed")

    @Remote("complete")
    def complete(self, agent, ref):
        return self._transition(agent, ref, "complete", ("active", "paused", "blocked"), "complete", "disarmed")

    def block(self, agent, ref, reason):
        if not isinstance(reason, dict):
            raise GoalError("invalid goal block reason", "GOAL_INVALID_BLOCK_REASON")
        return self._transition(agent, ref, "block", ("active",), "blocked", "disarmed", reason)

    @Remote("clear")
    def clear(self, agent, ref):
        cache = self._prepare(agent)
        current = self._expect(cache, ref)
        tombstone = {"id": current["id"], "revision": current["revision"] + 1}
        self._commit(agent, cache, {"kind": "goal/change", "version": 1, "operation": "clear",
            "cleared": tombstone, "clearedAt": max(int(time.time() * 1000), cache["state"]["updatedAt"])}, "disarmed")
        return copy.deepcopy(tombstone)
