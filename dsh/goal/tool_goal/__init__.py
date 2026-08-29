"""
Persisted same-session Goal Service & Tools (`@deepseek-ai/dsh-goal` & `@deepseek-ai/dsh-tool-goal`).
Provides long-running objective tracking, autonomous goal rounds, and `get_goal`, `create_goal`, `update_goal` tools.
"""

import time
from typing import Any, Dict, List, Optional, Union
import uuid

from dsh.cordis.plugin import Plugin
from dsh.core.session import Session, SessionStore
from dsh.goal.tool_goal.authority import (
    completion_authority,
    goal_tool_execution,
    require_direct_human,
)
from dsh.goal.tool_goal.wrapup import render_wrapup_context

UPDATE_ACTIONS = ["edit", "pause", "resume", "complete", "blocked"]

GET_DESCRIPTION = (
    "Read the current same-session goal, including its exact id/revision, objective, phase, completed "
    "continuation rounds, round limit, blocker reason when present, and whether another continuation is armed. "
    "Call this before updating a goal."
)

CREATE_DESCRIPTION = (
    "Create one persisted same-session completion goal when the current direct human request "
    "is a long-running objective that should continue across autonomous goal rounds. You may "
    "infer that intent without requiring the user to say \"create a goal\". Do not use this for "
    "trivial single-turn work. Execution rejects non-human and subagent authority."
)

UPDATE_DESCRIPTION = (
    "Update the exact current goal revision. edit, pause, and resume require a direct "
    "top-level human request. During an automatic continuation of the current goal, complete "
    "and blocked are also allowed. blocked is rejected before the configured minimum round count; the model remains "
    "responsible for judging that the same condition persisted across those rounds and must explain it in blocked_reason."
)


def guidance(blocked_after: int) -> str:
    return (
        "Use goal tools for one long-running completion objective in the current session. "
        "create_goal may infer goal intent from a direct human request in any language; do not "
        "create a goal for routine single-turn work. Call get_goal before update_goal and copy its "
        "exact goal_id and revision. After session resume or fork, an active goal is disarmed: when "
        "a human asks to continue or resume in any wording or language, use update_goal action "
        "resume to rearm it. Mark complete only when the objective is actually achieved. Mark "
        f"blocked only after the same blocking condition persists for at least {blocked_after} "
        "consecutive goal rounds, and report that concrete condition in blocked_reason; difficulty, uncertainty, "
        "or useful remaining work is not blocked."
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
        max_goal_rounds: int = 256,
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
                    goal_id=g_dict.get("id", f"goal-{str(uuid.uuid4())[:8]}"),
                    revision=g_dict.get("revision", 1),
                    objective=g_dict.get("objective", ""),
                    phase=g_dict.get("phase", "active"),
                    rounds_started=g_dict.get("roundsStarted", 1),
                    max_goal_rounds=g_dict.get("maxGoalRounds", 256),
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

    def __init__(self, ctx: Any, blocked_after_consecutive_rounds: int = 3, default_max_goal_rounds: int = 256):
        self.ctx = ctx
        self.blocked_after_consecutive_rounds = blocked_after_consecutive_rounds
        self.default_max_goal_rounds = default_max_goal_rounds

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

    def get(self, agent: Optional[Any] = None) -> Optional[GoalSnapshot]:
        return self.get_goal(agent=agent)

    def get_goal(self, agent: Optional[Any] = None) -> Optional[GoalSnapshot]:
        sess = self._resolve_session(agent)
        if not sess:
            return None
        return fold_goal_state(sess.events)

    def create(self, agent: Optional[Any] = None, request: Optional[Dict[str, Any]] = None, **kwargs) -> GoalSnapshot:
        req = request or kwargs
        obj = req.get("objective", "") if isinstance(req, dict) else kwargs.get("objective", "")
        max_rounds = req.get("maxGoalRounds", req.get("max_goal_rounds", self.default_max_goal_rounds)) if isinstance(req, dict) else kwargs.get("max_goal_rounds", self.default_max_goal_rounds)
        return self.create_goal(objective=obj, max_goal_rounds=max_rounds, agent=agent)

    def create_goal(
        self,
        objective: str,
        max_goal_rounds: int = 256,
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
        blocked_reason: Optional[Union[str, Dict[str, str]]] = None,
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
            if not blocked_reason:
                raise ValueError("blocked_reason is required with action blocked")
            msg = blocked_reason["message"] if isinstance(blocked_reason, dict) else str(blocked_reason)
            if not msg.strip():
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
            if isinstance(blocked_reason, dict):
                new_blocked = blocked_reason
            else:
                new_blocked = {"code": "model-reported", "message": str(blocked_reason)}

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
                b_msg = new_blocked["message"] if new_blocked else None
                wrapup_text = render_wrapup_context(new_obj, b_msg if action == "blocked" else None)
                self.ctx.emit("agent/wrapup-notice", {"agent": agent, "text": wrapup_text})

        return updated

    def pause(self, agent: Optional[Any], ref: Any) -> GoalSnapshot:
        gid = ref.id if hasattr(ref, "id") else ref["id"]
        rev = ref.revision if hasattr(ref, "revision") else ref["revision"]
        return self.update_goal(goal_id=gid, revision=rev, action="pause", agent=agent)

    def resume(self, agent: Optional[Any], ref: Any) -> GoalSnapshot:
        gid = ref.id if hasattr(ref, "id") else ref["id"]
        rev = ref.revision if hasattr(ref, "revision") else ref["revision"]
        return self.update_goal(goal_id=gid, revision=rev, action="resume", agent=agent)

    def complete(self, agent: Optional[Any], ref: Any) -> GoalSnapshot:
        gid = ref.id if hasattr(ref, "id") else ref["id"]
        rev = ref.revision if hasattr(ref, "revision") else ref["revision"]
        return self.update_goal(goal_id=gid, revision=rev, action="complete", agent=agent)

    def block(self, agent: Optional[Any], ref: Any, reason: Any) -> GoalSnapshot:
        gid = ref.id if hasattr(ref, "id") else ref["id"]
        rev = ref.revision if hasattr(ref, "revision") else ref["revision"]
        return self.update_goal(goal_id=gid, revision=rev, action="blocked", blocked_reason=reason, agent=agent)

    def clear(self, agent: Optional[Any], ref: Any) -> Dict[str, Any]:
        sess = self._resolve_session(agent)
        gid = ref.id if hasattr(ref, "id") else ref["id"]
        rev = ref.revision if hasattr(ref, "revision") else ref["revision"]
        tombstone = {"id": gid, "revision": rev + 1}
        if sess:
            sess.append("goal/change", {"operation": "clear", "cleared": tombstone}, ignorable=True)
        return tombstone


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
        if not ctx.has("goals"):
            goal_svc = GoalService(ctx, blocked_after_consecutive_rounds=self.blocked_after_consecutive_rounds)
            ctx.set_service("goals", goal_svc)

        if hasattr(ctx, "has") and ctx.has("systemPrompt"):
            sp = ctx.get("systemPrompt")
            if hasattr(sp, "section"):
                sp.section(
                    name="tool:goal",
                    order=114,
                    text=guidance(self.blocked_after_consecutive_rounds),
                )

        tools = ctx.get("tools")
        if not tools:
            return

        # 1. get_goal
        if hasattr(tools, "register_tool"):
            tools.register_tool({
                "name": "get_goal",
                "description": GET_DESCRIPTION,
                "parameters": {"type": "object", "properties": {}},
                "execute": self.handle_get_goal,
            })
        elif hasattr(tools, "register"):
            tools.register(
                name="get_goal",
                description=GET_DESCRIPTION,
                parameters={"type": "object", "properties": {}},
                handler=self.handle_get_goal,
            )

        # 2. create_goal
        create_params = {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "The concrete completion objective inferred from the direct human request.",
                },
                "max_goal_rounds": {
                    "type": "integer",
                    "description": "Optional positive safe-integer limit on automatic continuation rounds.",
                },
            },
            "required": ["objective"],
        }

        if hasattr(tools, "register_tool"):
            tools.register_tool({
                "name": "create_goal",
                "description": CREATE_DESCRIPTION,
                "parameters": create_params,
                "execute": self.handle_create_goal,
            })
        elif hasattr(tools, "register"):
            tools.register(
                name="create_goal",
                description=CREATE_DESCRIPTION,
                parameters=create_params,
                handler=self.handle_create_goal,
            )

        # 3. update_goal
        update_params = {
            "type": "object",
            "properties": {
                "goal_id": {"type": "string", "description": "Exact id returned by get_goal."},
                "revision": {"type": "integer", "description": "Exact positive revision returned by get_goal."},
                "action": {
                    "type": "string",
                    "enum": UPDATE_ACTIONS,
                    "description": "edit | pause | resume | complete | blocked",
                },
                "objective": {"type": "string", "description": "Replacement objective; valid only with action edit."},
                "max_goal_rounds": {"type": "integer", "description": "Replacement cap; valid only with action edit."},
                "blocked_reason": {
                    "type": "string",
                    "description": "Concrete blocking condition; required only with action blocked.",
                },
            },
            "required": ["goal_id", "revision", "action"],
        }

        if hasattr(tools, "register_tool"):
            tools.register_tool({
                "name": "update_goal",
                "description": UPDATE_DESCRIPTION,
                "parameters": update_params,
                "execute": self.handle_update_goal,
            })
        elif hasattr(tools, "register"):
            tools.register(
                name="update_goal",
                description=UPDATE_DESCRIPTION,
                parameters=update_params,
                handler=self.handle_update_goal,
            )

        # Register /goal command if commands service is mounted
        if ctx.has("commands"):
            cmd_svc = ctx.get("commands")
            if hasattr(cmd_svc, "register"):
                def execute_goal_command(invocation: Any) -> str:
                    raw = getattr(invocation, "raw_input", str(invocation))
                    tokens = raw.strip().split(None, 1)
                    sub = tokens[0].lower() if tokens else "show"
                    goal_svc = ctx.get("goals")
                    if sub == "clear":
                        g = goal_svc.get_goal()
                        if g:
                            goal_svc.clear(None, g)
                            return "Goal cleared."
                        return "No goal to clear."
                    elif sub == "pause":
                        g = goal_svc.get_goal()
                        if g:
                            goal_svc.update_goal(g.id, g.revision, "pause")
                            return "Goal paused."
                        return "No goal is currently set."
                    elif sub == "resume":
                        g = goal_svc.get_goal()
                        if g:
                            goal_svc.update_goal(g.id, g.revision, "resume")
                            return "Goal resumed."
                        return "No goal is currently set."
                    elif sub == "edit":
                        if len(tokens) > 1 and tokens[1].strip():
                            g = goal_svc.get_goal()
                            if g:
                                goal_svc.update_goal(g.id, g.revision, "edit", objective=tokens[1].strip())
                                return "Goal updated."
                        return "Goal editing requires a replacement objective."
                    else:
                        if raw.strip():
                            g = goal_svc.get_goal()
                            if g and g.phase != "complete":
                                return f"A goal is already {g.phase}. Use /goal edit <objective> to change it."
                            new_g = goal_svc.create_goal(objective=raw.strip())
                            return f"Goal created: {new_g.objective}"
                        else:
                            g = goal_svc.get_goal()
                            if not g:
                                return "No goal is currently set."
                            return f"Status: {g.phase}\nObjective: {g.objective}"

                cmd_svc.register(
                    name="goal",
                    description="set or view the goal for a long-running task",
                    handler=execute_goal_command,
                )

        # Hook /goal command in pre-step for natural input
        ctx.on("agent/pre-step", self._hook_goal_slash_command)

    def handle_get_goal(self, ctx: Optional[Any] = None, **kwargs) -> Dict[str, Any]:
        context = ctx or self.ctx
        goal_svc: GoalService = context.get("goals")
        if not goal_svc:
            return {"goal": None}
        goal = goal_svc.get_goal()
        if not goal:
            return {"goal": None}
        return {"goal": goal.to_dict(), "activation": goal.activation}

    def handle_create_goal(
        self, objective: str = "", max_goal_rounds: int = 256, ctx: Optional[Any] = None, **kwargs
    ) -> Dict[str, Any]:
        context = ctx or self.ctx
        exec_ctx = kwargs.get("exec") or context
        require_direct_human(context, exec_ctx)
        obj = objective or kwargs.get("objective", "")
        max_rounds = max_goal_rounds if "max_goal_rounds" in kwargs or max_goal_rounds != 256 else kwargs.get("max_goal_rounds", 256)
        goal_svc: GoalService = context.get("goals")
        if not goal_svc:
            return {"error": "Goal service not available"}
        goal = goal_svc.create_goal(objective=obj, max_goal_rounds=max_rounds)
        return {"goal": goal.to_dict(), "activation": goal.activation}

    def handle_update_goal(
        self,
        goal_id: str = "",
        revision: int = 1,
        action: str = "",
        objective: Optional[str] = None,
        max_goal_rounds: Optional[int] = None,
        blocked_reason: Optional[str] = None,
        ctx: Optional[Any] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        context = ctx or self.ctx
        gid = goal_id or kwargs.get("goal_id", "")
        rev = revision if "revision" in kwargs or revision != 1 else kwargs.get("revision", 1)
        act = action or kwargs.get("action", "")
        obj = objective or kwargs.get("objective")
        max_rounds = max_goal_rounds or kwargs.get("max_goal_rounds")
        b_reason = blocked_reason or kwargs.get("blocked_reason")

        exec_ctx = kwargs.get("exec") or context
        if act in ("edit", "pause", "resume"):
            require_direct_human(context, exec_ctx)
        elif act in ("complete", "blocked"):
            completion_authority(context, exec_ctx)

        goal_svc: GoalService = context.get("goals")
        if not goal_svc:
            return {"error": "Goal service not available"}
        goal = goal_svc.update_goal(
            goal_id=gid,
            revision=rev,
            action=act,
            objective=obj,
            max_goal_rounds=max_rounds,
            blocked_reason=b_reason,
            is_goal_round=kwargs.get("is_goal_round", False),
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
