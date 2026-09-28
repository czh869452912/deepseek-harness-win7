"""Same-session continuation with durable checkpoints and exact reservation fences."""
import asyncio
import json
import logging

from dsh.cordis.plugin import Plugin
from dsh.cordis.fiber import FiberState
from dsh.llm.message import create_user_message
from dsh.goal.fold import goal_ref

logger = logging.getLogger(__name__)


def render_goal_round_prompt(goal, round_number):
    return [{"type": "text", "text": '<goal_round>\nObjective: ' + json.dumps(goal["objective"], ensure_ascii=False)
        + '\nRound: {}/{}\n\n'.format(round_number, goal["maxGoalRounds"])
        + 'Continue working toward the objective in this same session. Treat the current workspace, '
        + 'tool results, and durable session state as authoritative; inspect them instead of assuming '
        + 'earlier narration is still current. Make concrete progress and verify the result. Before '
        + 'claiming completion, gather evidence that the whole objective is achieved, read the current '
        + 'goal, and mark it complete. If work remains, leave the goal active for the next round. Follow '
        + 'the configured goal-tool policy before reporting a blocker.\n</goal_round>'}]


def is_round(source):
    return source.get("kind") == "goal" and isinstance(source.get("round"), (int, float)) and source["round"] > 0


def same_round(source, attempt):
    return all(source.get(key) == attempt.get(key) for key in ("goalId", "revision", "round"))


def same_queued(message, attempt):
    source = message.get("source", {})
    return is_round(source) and same_round(source, attempt) and message["content"] == attempt["content"]


class GoalRoundDriver(Plugin):
    id = "goal-round-driver"
    inject = ["agents", "goals", "sessions"]

    def apply(self, ctx):
        self.ctx, self.states = ctx, {}
        def lifecycle():
            ctx.on("agent/error", lambda payload: self.disarm(self.state(payload["agent"])))
            ctx.on("agent/created", lambda payload: self.state(payload["agent"]))
            ctx.on("agent/disposed", lambda payload: self.states.pop(payload["agent"], None))
            ctx.on("agent/session-start", self.session_start)
            ctx.on("agent/status", self.status)
            ctx.on("goal/changed", self.changed)
            ctx.on("agent/inbox/inserted", self.inserted)
            ctx.on("agent/inbox/claimed", lambda payload: self.inbox_phase(payload, "phase", "claimed"))
            ctx.on("agent/inbox/discarded", lambda payload: self.inbox_phase(payload, "cancelled", True))
            ctx.on("session/event", self.event)
            ctx.on("agent/pre-step", self.pre_step)
            for agent in ctx.get("agents").list():
                self.disarm(self.state(agent))
            yield self.close
        ctx.effect(lifecycle, "goal-round-driver lifecycle")

    def state(self, agent):
        if agent not in self.states:
            self.states[agent] = {"agent": agent, "attempt": None, "competing": False, "checkpoint": False,
                                  "requested": False, "run": None, "stopping": False}
        return self.states[agent]

    def current(self, state):
        agent = state["agent"]
        return self.ctx.get("goals").get(agent) if self.ctx.get("agents").get(agent.id) is agent else None

    def ready(self, state):
        return (self.ctx.fiber.state == FiberState.ACTIVE and not state["stopping"]
                and self.ctx.get("agents").get(state["agent"].id) is state["agent"]
                and state["agent"].status == "idle" and not state["competing"])

    def disarm(self, state):
        try:
            goal = self.current(state)
            if goal and goal["activation"] == "armed":
                self.ctx.get("goals").disarm(state["agent"])
        except Exception:
            logger.warning("could not disarm goal for %s", state["agent"].id, exc_info=True)

    async def drive(self, state):
        if not self.ready(state):
            return
        agent = state["agent"]
        if state["checkpoint"]:
            state["checkpoint"] = False
            try:
                await self.ctx.get("sessions").flush(agent.session)
            except Exception:
                logger.warning("goal durability checkpoint failed", exc_info=True)
                self.disarm(state)
                return
            if not self.ready(state) or state["checkpoint"]:
                return
        if state["attempt"] is not None:
            state.update(attempt=None, checkpoint=True, requested=True)
            return
        goal = self.current(state)
        if not goal or goal["phase"] != "active" or goal["activation"] != "armed":
            return
        if goal["roundsStarted"] >= goal["maxGoalRounds"]:
            self.ctx.get("goals").block(agent, goal_ref(goal), {"code": "round-limit",
                "message": "Goal reached its configured limit of {} rounds.".format(goal["maxGoalRounds"])})
            return
        round_number = goal["roundsStarted"] + 1
        content = render_goal_round_prompt(goal, round_number)
        source = {"kind": "goal", "goalId": goal["id"], "revision": goal["revision"], "round": round_number}
        message = create_user_message({"content": content, "source": source})
        state["attempt"] = dict(source, messageId=message["id"], content=content, phase="queued", cancelled=False, stale=False)
        try:
            agent.followup(message)
        except Exception as error:
            state["attempt"] = None
            latest = self.current(state)
            if latest and goal_ref(latest) == goal_ref(goal) and latest["phase"] == "active" and latest["activation"] == "armed":
                self.ctx.get("goals").block(agent, goal_ref(latest), {"code": "queue-failed",
                    "message": "Could not queue goal round {}: {}".format(round_number, error)})

    def request(self, state):
        if state["stopping"]:
            return
        state["requested"] = True
        if state["run"] is not None:
            return
        async def run():
            try:
                while state["requested"] and not state["stopping"]:
                    state["requested"] = False
                    try:
                        await self.drive(state)
                    except Exception:
                        logger.warning("goal driver failed", exc_info=True)
                        self.disarm(state)
            finally:
                state["run"] = None
                if state["requested"] and not state["stopping"]:
                    self.request(state)
        # Task creation captures the cleared ContextVar, not the triggering model turn.
        try:
            state["run"] = self.ctx.get("agents").without_initiator(lambda: asyncio.create_task(run()))
        except Exception:
            self.disarm(state)

    def session_start(self, payload):
        self.state(payload["agent"]).update(attempt=None, competing=False, checkpoint=False)

    def status(self, payload):
        state = self.state(payload["agent"])
        if payload["status"] != "idle":
            return
        state["competing"] = False
        attempt, goal = state["attempt"], self.current(state)
        if (attempt and (attempt["phase"] in ("queued", "claimed") or attempt["cancelled"])
                and goal and goal["phase"] == "active" and goal["activation"] == "armed"):
            state["attempt"] = None
            try:
                self.ctx.get("goals").pause(state["agent"], goal_ref(goal))
            except Exception:
                self.disarm(state)
        self.request(state)

    def changed(self, payload):
        state = self.state(payload["agent"])
        state["checkpoint"] = True
        self.request(state)

    def inserted(self, payload):
        agent, message = payload["agent"], payload["message"]
        if not any(row["id"] == message["id"] for row in agent.inbox.next_turn):
            return
        state = self.state(agent)
        attempt = state["attempt"]
        if attempt and same_queued(message, attempt):
            return
        state["competing"] = True
        if attempt and attempt["phase"] == "queued":
            attempt["stale"] = True

    def inbox_phase(self, payload, key, value):
        attempt = self.state(payload["agent"])["attempt"]
        if attempt and same_queued(payload["message"], attempt):
            attempt[key] = value

    def event(self, session, event):
        agent = self.ctx.get("agents").get(session.id)
        if agent is None or agent.session is not session:
            return
        state = self.state(agent)
        attempt = state["attempt"]
        if event["type"] == "user/message":
            if attempt and event["data"]["id"] == attempt["messageId"]:
                attempt["phase"] = "admitted"
        elif event["type"] == "turn/end":
            reason = event["data"]["reason"]["kind"]
            if reason == "max-tokens":
                self.disarm(state)
            elif reason == "aborted":
                if attempt and attempt["phase"] in ("claimed", "admitted"):
                    attempt["cancelled"] = True
                else:
                    self.disarm(state)

    def valid(self, state, message):
        attempt, goal, source = state["attempt"], self.current(state), message["source"]
        return (self.ctx.fiber.state == FiberState.ACTIVE and not state["stopping"] and attempt
                and attempt["phase"] == "claimed" and not attempt["stale"] and same_queued(message, attempt)
                and goal and goal["id"] == source["goalId"] and goal["revision"] == source["revision"]
                and goal["phase"] == "active" and goal["activation"] == "armed" and source["round"] == goal["roundsStarted"] + 1)

    def restore(self, agent, messages, message_id):
        for message in reversed(messages):
            source = message.get("source", {})
            if message["id"] == message_id or source.get("kind") == "goal" and source.get("round") == 0:
                continue
            if not any(row["id"] == message["id"] for row in agent.inbox.next_step + agent.inbox.next_turn):
                agent.inbox.prepend("next-step", message)

    async def pre_step(self, payload, next_fn):
        submitted = next((row for row in payload["messages"] if is_round(row.get("source", {}))), None)
        if submitted is None:
            return await next_fn()
        agent = payload["agent"]
        state = self.state(agent)
        def valid():
            try:
                return self.valid(state, submitted)
            except Exception:
                self.disarm(state)
                return False
        if not valid():
            attempt = state["attempt"]
            if attempt and same_round(submitted["source"], attempt):
                attempt["stale"] = True
                state["attempt"] = None
            self.restore(agent, payload["messages"], submitted["id"])
            self.request(state)
            return {"kind": "reject"}
        try:
            decision = await next_fn()
        except Exception:
            if not agent.is_cancelled():
                state["attempt"] = None
                self.request(state)
            raise
        if agent.is_cancelled():
            if decision.get("kind") != "reject":
                self.restore(agent, decision["messages"], submitted["id"])
            return decision
        if decision.get("kind") == "reject":
            state["attempt"] = None
            goal = self.current(state)
            if goal and goal["id"] == submitted["source"]["goalId"] and goal["revision"] == submitted["source"]["revision"] and goal["phase"] == "active" and goal["activation"] == "armed":
                self.ctx.get("goals").block(agent, goal_ref(goal), {"code": "prompt-rejected", "message": "Goal round was rejected before entering its step."})
            return decision
        if not valid():
            state["attempt"] = None
            self.restore(agent, decision["messages"], submitted["id"])
            self.request(state)
            return {"kind": "reject"}
        return dict(decision, startsRequestSeries=True)

    async def close(self):
        waits = []
        for state in list(self.states.values()):
            state["stopping"] = True
            self.disarm(state)
            if state["attempt"]:
                state["attempt"]["stale"] = True
                if state["agent"].status == "running":
                    state["agent"].cancel({"kind": "parent"})
                    waits.append(state["agent"].when_idle())
            if state["run"] is not None:
                waits.append(state["run"])
        await asyncio.gather(*waits, return_exceptions=True)
        self.states.clear()
