"""
Persisted same-session Goal Service & Tools (`@deepseek-ai/dsh-goal` & `@deepseek-ai/dsh-tool-goal`).
Provides long-running objective tracking, autonomous goal rounds, and `get_goal`, `create_goal`, `update_goal` tools.
"""

import time
from typing import Any, Dict, List, Optional
import uuid

from dsh.cordis.plugin import Plugin
from dsh.core.session import Session


def render_wrapup_context(objective: str, blocked_reason: Optional[str] = None) -> str:
    """Render wrapup user notice after goal completion or block."""
    if blocked_reason:
        return (
            f"The goal '{objective}' was marked blocked: {blocked_reason}. "
            "Summarize the work done, the blocking condition, and any recommendations for the user."
        )
    return (
        f"The goal '{objective}' is complete. "
        "Summarize what was accomplished and any next steps for the user."
    )


class GoalSnapshot:
    """Snapshot representation of a session goal."""

    def __init__(
        self,
        goal_id: str,
        revision: int,
        objective: str,
        phase: str = "active",  # active, paused, blocked, complete
        rounds_started: int = 1,
        max_goal_rounds: int = 20,
        blocked_reason: Optional[Dict[str, str]] = None,
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
        activation: str = "armed",
    ):
        self.id = goal_id
        self.revision = revision
        self.objective = objective
        self.phase = phase
        self.rounds_started = rounds_started
        self.max_goal_rounds = max_goal_rounds
        self.blocked_reason = blocked_reason
        self.created_at = created_at or int(time.time() * 1000)
        self.updated_at = updated_at or int(time.time() * 1000)
        self.activation = activation

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": self.id,
            "revision": self.revision,
            "objective": self.objective,
            "phase": self.phase,
            "roundsStarted": self.rounds_started,
            "maxGoalRounds": self.max_goal_rounds,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if self.blocked_reason:
            res["blockedReason"] = self.blocked_reason
        return res


def fold_goal_state(events: List[Any]) -> Optional[GoalSnapshot]:
    """Fold latest goal snapshot from session events."""
    current_goal: Optional[GoalSnapshot] = None
    for event in events:
        evt_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
        evt_data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
        if evt_type == "goal/change":
            op = evt_data.get("operation")
            if op == "clear":
                current_goal = None
            else:
                g_dict = evt_data.get("goal", {})
                current_goal = GoalSnapshot(
                    goal_id=g_dict.get("id", str(uuid.uuid4())[:8]),
                    revision=g_dict.get("revision", 1),
                    objective=g_dict.get("objective", ""),
                    phase=g_dict.get("phase", "active"),
                    rounds_started=g_dict.get("roundsStarted", 1),
                    max_goal_rounds=g_dict.get("maxGoalRounds", 20),
                    blocked_reason=g_dict.get("blockedReason"),
                    created_at=g_dict.get("createdAt"),
                    updated_at=g_dict.get("updatedAt"),
                    activation=g_dict.get("activation", "armed"),
                )
    return current_goal


class GoalService:
    """
    Goal Service registered at `ctx.goals`.
    Manages same-session long-running goal tracking with CAS concurrency.
    """

    def __init__(self, ctx: Any, blocked_after_consecutive_rounds: int = 3):
        self.ctx = ctx
        self.blocked_after_consecutive_rounds = blocked_after_consecutive_rounds

    def _resolve_session(self, agent: Optional[Any] = None) -> Optional[Session]:
        if agent and hasattr(agent, "session") and agent.session:
            return agent.session
        if self.ctx and self.ctx.has("agents"):
            agents_svc = self.ctx.get("agents")
            if hasattr(agents_svc, "current_initiator"):
                initiator = agents_svc.current_initiator()
                if initiator and hasattr(initiator, "session"):
                    return initiator.session
        if self.ctx and self.ctx.has("sessions"):
            sessions_svc = self.ctx.get("sessions")
            if isinstance(sessions_svc, Session):
                return sessions_svc
            if hasattr(sessions_svc, "get"):
                s = sessions_svc.get("default-session")
                if s:
                    return s
                if hasattr(sessions_svc, "_sessions") and sessions_svc._sessions:
                    return next(iter(sessions_svc._sessions.values()))
        return None

    def get_goal(self, agent: Optional[Any] = None) -> Optional[GoalSnapshot]:
        sess = self._resolve_session(agent)
        if not sess:
            return None
        return fold_goal_state(sess.events)

    def create_goal(
        self,
        objective: str,
        max_goal_rounds: int = 20,
        agent: Optional[Any] = None,
    ) -> GoalSnapshot:
        sess = self._resolve_session(agent)
        if not sess:
            raise RuntimeError("GoalService: no active session found to create goal.")

        goal_id = f"goal-{str(uuid.uuid4())[:8]}"
        now = int(time.time() * 1000)
        snapshot = GoalSnapshot(
            goal_id=goal_id,
            revision=1,
            objective=objective,
            phase="active",
            rounds_started=1,
            max_goal_rounds=max_goal_rounds,
            created_at=now,
            updated_at=now,
            activation="armed",
        )

        sess.append("goal/change", {
            "operation": "create",
            "goal": snapshot.to_dict(),
        }, ignorable=True)

        if self.ctx:
            self.ctx.emit("goal/changed", {"agent": agent, "goal": snapshot.to_dict()})

        return snapshot

    def update_goal(
        self,
        goal_id: str,
        revision: int,
        action: str,  # edit, pause, resume, complete, blocked
        objective: Optional[str] = None,
        max_goal_rounds: Optional[int] = None,
        blocked_reason: Optional[str] = None,
        is_goal_round: bool = False,
        agent: Optional[Any] = None,
    ) -> GoalSnapshot:
        sess = self._resolve_session(agent)
        if not sess:
            raise RuntimeError("GoalService: no active session found to update goal.")

        current = fold_goal_state(sess.events)
        if not current or current.id != goal_id:
            raise ValueError(f"Goal '{goal_id}' not found in active session.")

        if current.revision != revision:
            raise ValueError(f"Revision mismatch for goal '{goal_id}': expected {current.revision}, got {revision}")

        if action == "blocked":
            if not blocked_reason or not blocked_reason.strip():
                raise ValueError("blocked_reason is required with action blocked")
            if is_goal_round and current.rounds_started < self.blocked_after_consecutive_rounds:
                raise ValueError(
                    f"blocked requires at least {self.blocked_after_consecutive_rounds} consecutive goal rounds; "
                    f"current round is {current.rounds_started}"
                )

        new_rev = revision + 1
        now = int(time.time() * 1000)

        new_obj = objective if (action == "edit" and objective) else current.objective
        new_max = max_goal_rounds if (action == "edit" and max_goal_rounds) else current.max_goal_rounds
        new_phase = current.phase
        new_blocked = current.blocked_reason
        new_activation = current.activation

        if action == "pause":
            new_phase = "paused"
            new_activation = "disarmed"
        elif action == "resume":
            new_phase = "active"
            new_activation = "armed"
        elif action == "complete":
            new_phase = "complete"
            new_activation = "disarmed"
        elif action == "blocked":
            new_phase = "blocked"
            new_activation = "disarmed"
            new_blocked = {"code": "model-reported", "message": blocked_reason or "Blocked"}

        updated = GoalSnapshot(
            goal_id=current.id,
            revision=new_rev,
            objective=new_obj,
            phase=new_phase,
            rounds_started=current.rounds_started,
            max_goal_rounds=new_max,
            blocked_reason=new_blocked,
            created_at=current.created_at,
            updated_at=now,
            activation=new_activation,
        )

        sess.append("goal/change", {
            "operation": action,
            "goal": updated.to_dict(),
        }, ignorable=True)

        if self.ctx:
            self.ctx.emit("goal/changed", {"agent": agent, "goal": updated.to_dict()})

            if action in ("complete", "blocked") and is_goal_round:
                wrapup_text = render_wrapup_context(new_obj, blocked_reason if action == "blocked" else None)
                self.ctx.emit("agent/wrapup-notice", {"agent": agent, "text": wrapup_text})

        return updated


class ToolGoalPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-goal`: Exposes `get_goal`, `create_goal`, `update_goal` tools and `/goal` command.
    """

    id = "tool-goal"
    name = "@deepseek-ai/dsh-tool-goal"
    inject = ["tools"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.blocked_after_consecutive_rounds = int(cfg.get("blockedAfterConsecutiveRounds", 3))

    def apply(self, ctx: Any) -> None:
        goal_svc = GoalService(ctx, blocked_after_consecutive_rounds=self.blocked_after_consecutive_rounds)
        ctx.set_service("goals", goal_svc)

        tools = ctx.get("tools")
        if not tools:
            return

        # 1. get_goal
        tools.register(
            name="get_goal",
            description="Read the current same-session goal, including its exact id/revision, objective, phase, completed continuation rounds, round limit, and activation status.",
            parameters={"type": "object", "properties": {}},
            handler=self.handle_get_goal,
        )

        # 2. create_goal
        tools.register(
            name="create_goal",
            description="Create one persisted same-session completion goal when the request is a long-running multi-turn objective.",
            parameters={
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": "The concrete completion objective inferred from the direct human request.",
                    },
                    "max_goal_rounds": {
                        "type": "integer",
                        "description": "Optional positive integer limit on autonomous continuation rounds (default 20).",
                    },
                },
                "required": ["objective"],
            },
            handler=self.handle_create_goal,
        )

        # 3. update_goal
        tools.register(
            name="update_goal",
            description="Update the exact current goal revision. edit, pause, resume, complete, or blocked. blocked is rejected before 3 consecutive rounds.",
            parameters={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "Exact id returned by get_goal."},
                    "revision": {"type": "integer", "description": "Exact positive revision returned by get_goal."},
                    "action": {
                        "type": "string",
                        "enum": ["edit", "pause", "resume", "complete", "blocked"],
                        "description": "edit | pause | resume | complete | blocked",
                    },
                    "objective": {"type": "string", "description": "Replacement objective (action: edit)."},
                    "max_goal_rounds": {"type": "integer", "description": "Replacement round cap (action: edit)."},
                    "blocked_reason": {"type": "string", "description": "Concrete blocking condition (required with action: blocked)."},
                },
                "required": ["goal_id", "revision", "action"],
            },
            handler=self.handle_update_goal,
        )

        # Hook /goal command
        ctx.on("agent/pre-step", self._hook_goal_slash_command)

    def handle_get_goal(self, ctx: Optional[Any] = None) -> Dict[str, Any]:
        context = ctx or self.ctx
        goal_svc: GoalService = context.get("goals")
        if not goal_svc:
            return {"goal": None}
        goal = goal_svc.get_goal()
        if not goal:
            return {"goal": None}
        return {"goal": goal.to_dict(), "activation": goal.activation}

    def handle_create_goal(self, objective: str, max_goal_rounds: int = 20, ctx: Optional[Any] = None) -> Dict[str, Any]:
        context = ctx or self.ctx
        goal_svc: GoalService = context.get("goals")
        if not goal_svc:
            return {"error": "Goal service not available"}
        goal = goal_svc.create_goal(objective=objective, max_goal_rounds=max_goal_rounds)
        return {"goal": goal.to_dict(), "activation": goal.activation}

    def handle_update_goal(
        self,
        goal_id: str,
        revision: int,
        action: str,
        objective: Optional[str] = None,
        max_goal_rounds: Optional[int] = None,
        blocked_reason: Optional[str] = None,
        ctx: Optional[Any] = None,
    ) -> Dict[str, Any]:
        context = ctx or self.ctx
        goal_svc: GoalService = context.get("goals")
        if not goal_svc:
            return {"error": "Goal service not available"}
        goal = goal_svc.update_goal(
            goal_id=goal_id,
            revision=revision,
            action=action,
            objective=objective,
            max_goal_rounds=max_goal_rounds,
            blocked_reason=blocked_reason,
        )
        return {"goal": goal.to_dict(), "activation": goal.activation}

    async def _hook_goal_slash_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        messages = payload.get("messages", [])
        if not messages:
            return payload

        last_user_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg
                break

        if last_user_msg and isinstance(last_user_msg.get("content"), str):
            text = last_user_msg["content"].strip()
            if text.startswith("/goal"):
                tokens = text.split(None, 1)
                goal_svc: GoalService = self.ctx.get("goals")
                if goal_svc:
                    if len(tokens) > 1 and tokens[1].strip():
                        arg = tokens[1].strip()
                        if arg.lower() == "pause":
                            g = goal_svc.get_goal()
                            if g:
                                goal_svc.update_goal(g.id, g.revision, "pause")
                                last_user_msg["content"] += "\n\n[Goal Notice: Current goal paused.]"
                        elif arg.lower() == "resume":
                            g = goal_svc.get_goal()
                            if g:
                                goal_svc.update_goal(g.id, g.revision, "resume")
                                last_user_msg["content"] += "\n\n[Goal Notice: Goal resumed.]"
                        else:
                            # Start new goal with objective
                            g = goal_svc.create_goal(objective=arg)
                            last_user_msg["content"] = f"{arg}\n\n[Goal Active: '{arg}']"
                    else:
                        g = goal_svc.get_goal()
                        status_str = f"Goal: {g.objective} (Phase: {g.phase})" if g else "No active goal"
                        last_user_msg["content"] += f"\n\n[Goal Status: {status_str}]"

        return payload

