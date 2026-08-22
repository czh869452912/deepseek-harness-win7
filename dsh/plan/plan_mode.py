"""
Plan Mode state machine (`@deepseek-ai/dsh-plan-mode`).
Provides logged per-agent collaboration state: while active, a deployment-owned guidance section
is included in each model request, and `exit_plan_mode` presents the completed plan for user review.
"""

import re
from typing import Any, Dict, List, Optional, Union

from dsh.cordis.plugin import Plugin
from dsh.core.session import Session, SessionEvent

EXIT_PLAN_MODE = "exit_plan_mode"
REVIEW_ID = "plan-review"
APPROVE_LABEL = "Approve"
KEEP_PLANNING_LABEL = "Keep planning"

EXIT_DESCRIPTION = (
    "Use only in plan mode. Present your plan for the user's review and, on approval, leave plan mode. "
    "Send the COMPLETE plan as markdown, starting with a # heading that names it. "
    "The user may approve (carry out the plan from your next step) or keep "
    "planning — their feedback comes back in the tool result; revise and present again."
)

DEFAULT_PLAN_GUIDANCE = """
You are in plan mode. Stay in plan mode until exit_plan_mode succeeds or the user switches the session mode. Imperative language to implement changes means plan the implementation, not execute it. A user's conversational agreement — including an answer confirming something you asked — approves nothing and does not end plan mode; fold the confirmed decision into the plan and submit it through exit_plan_mode.

Explore first. Use non-mutating reads, searches, static analysis, and checks to ground the plan in the actual repository. Do not edit or write files, change configuration, run formatters or code generation that rewrites tracked files, commit, or otherwise carry out the plan. Prefer existing functions and patterns over new machinery.

The tool catalog stays the same across modes for request-cache stability. These plan-mode rules override any later tool description or guidance that suggests using mutation tools; those tools remain listed to keep the tool catalog unchanged. Do not use todo_write to track this planning phase: it tracks implementation after an approved plan, while the plan itself belongs in exit_plan_mode.

Resolve discoverable facts by inspection. Use ask_user_question only for user-owned choices or material ambiguity that inspection cannot answer. Do not ask the user where code lives or how current behavior works when you can find out.

Make the plan decision-complete: state the goal and success criteria; group implementation changes by subsystem; identify public API, schema, and data-flow changes; cover edge cases, failure modes, tests, acceptance criteria, and explicit assumptions. Keep it concise enough to review but detailed enough that another engineer can implement it without making design decisions.

When ready, call exit_plan_mode with the complete plan markdown, starting with a # title. Make exit_plan_mode the only and final tool call in that assistant response: it presents the plan for approval, and implementation begins only in a later step after approval. Do not paste the final plan as a plain reply or ask "should I proceed?" through prose or ask_user_question. If review rejects it, incorporate the feedback and present again. If the review channel is unavailable or aborted, stay in plan mode and ask the user to switch modes manually; do not proceed with implementation.
""".strip()


def resolve_config(config: Union[str, Dict[str, Any]]) -> Dict[str, str]:
    if isinstance(config, str):
        section = config
    elif isinstance(config, dict):
        section = config.get("section", DEFAULT_PLAN_GUIDANCE)
    else:
        section = DEFAULT_PLAN_GUIDANCE
    if not isinstance(section, str) or not section.strip():
        section = DEFAULT_PLAN_GUIDANCE
    return {"section": section}


def fold_plan_mode(events: List[Any], end: Optional[int] = None) -> bool:
    """
    Whether plan mode is active after the specified event prefix.
    The last `plan/mode` event wins; default is False.
    """
    active = False
    limit = len(events) if end is None else end
    for i, event in enumerate(events):
        if i >= limit:
            break
        evt_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
        evt_data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
        if evt_type == "plan/mode":
            if isinstance(evt_data, dict):
                active = bool(evt_data.get("active", False))
            else:
                active = bool(getattr(evt_data, "active", False))
    return active


def first_heading(plan: str) -> Optional[str]:
    """Find the first markdown heading in plan text."""
    for line in plan.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line.strip())
        if match:
            return match.group(1)
    return None


class PlanModeController:
    """
    Plan Mode Service registered at `ctx.plan_mode`.
    Owns logged plan state, applies guidance during prompt assembly,
    and handles `exit_plan_mode` review transitions.
    """

    def __init__(self, ctx: Any, section: Optional[str] = None):
        self.ctx = ctx
        self.section = section or DEFAULT_PLAN_GUIDANCE
        self._pending_intents: Dict[str, Dict[str, Any]] = {}  # session_id -> {active, narrate}

        # System prompt section plan:policy
        if hasattr(ctx, "systemPrompt") and hasattr(ctx.systemPrompt, "section"):
            ctx.systemPrompt.section(
                name="plan:policy",
                order=50,
                text=lambda context: self.section if self.is_active() else "",
            )

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

    def is_active(self, session: Optional[Session] = None) -> bool:
        sess = session or self._resolve_session()
        if not sess:
            return False
        pending = self._pending_intents.get(sess.id)
        if pending is not None:
            return bool(pending.get("active", False))
        return fold_plan_mode(sess.events)

    def get_state(self, agent: Optional[Any] = None) -> Dict[str, Any]:
        sess = self._resolve_session(agent)
        if not sess:
            return {"active": False}
        active = fold_plan_mode(sess.events)
        pending = self._pending_intents.get(sess.id)
        if pending is not None:
            return {"active": active, "pending": pending.get("active", False)}
        return {"active": active}

    def set(self, agent: Optional[Any], active: bool) -> str:
        return self.set_active(active, agent=agent)

    def set_active(self, active: bool, agent: Optional[Any] = None) -> str:
        sess = self._resolve_session(agent)
        if not sess:
            return "noop"

        current_active = fold_plan_mode(sess.events)
        pending = self._pending_intents.get(sess.id)
        target = pending.get("active") if pending is not None else current_active

        if active == target:
            return "noop"

        self._pending_intents[sess.id] = {"active": active, "narrate": True}
        sess.append("plan/mode", {"active": active}, ignorable=True)
        self._pending_intents.pop(sess.id, None)
        return "committed"

    def on_prompt_assemble(self, prompt: str) -> str:
        """Inject plan guidance section if plan mode is active."""
        if self.is_active():
            return prompt + f"\n\n[Plan Mode Active]\n{self.section}\n"
        return prompt

    async def on_pre_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Commit pending plan mode transitions and handle messages."""
        agent = payload.get("agent")
        sess = self._resolve_session(agent)
        if not sess:
            return payload

        pending = self._pending_intents.pop(sess.id, None)
        if pending is not None:
            target = pending.get("active", False)
            if target != fold_plan_mode(sess.events):
                sess.append("plan/mode", {"active": target}, ignorable=True)

        return payload

    async def handle_exit_plan_mode(self, plan: str = "", ctx: Optional[Any] = None, **kwargs) -> Any:
        """Execute exit_plan_mode tool call."""
        context = ctx or self.ctx
        plan_text = plan or kwargs.get("plan", "")
        sess = self._resolve_session()

        if not self.is_active(sess):
            return "Error: exit_plan_mode is only available when plan mode is active"

        plan_clean = plan_text.strip()
        # TS regex: /^#\s+\S/
        if not re.match(r"^#\s+\S", plan_clean):
            return "Error: exit_plan_mode requires a non-empty markdown plan starting with a # heading"

        # Present plan for user review
        heading = first_heading(plan_clean) or "Plan Review"
        ask_user_tool = context.get("tools").get_tool("ask_user_question") if context and context.has("tools") else None

        if ask_user_tool:
            res = await context.get("tools").execute_tool(
                "ask_user_question",
                {
                    "questions": [{
                        "id": REVIEW_ID,
                        "question": f"Approve this plan and leave plan mode?\n\n{plan_clean}",
                        "header": "Plan Review",
                        "options": [
                            {"label": APPROVE_LABEL, "description": "Leave plan mode; the plan is carried out from the next step."},
                            {"label": KEEP_PLANNING_LABEL, "description": "Stay in plan mode; feedback goes back to the model."}
                        ]
                    }]
                }
            )

            if APPROVE_LABEL in str(res):
                self.set_active(False)
                return f"Plan approved — plan mode exited; carry out the plan starting with your next step."
            else:
                return f"The user chose to keep planning; their feedback: {res}"
        else:
            self.set_active(False)
            return "Plan approved — plan mode exited; carry out the plan starting with your next step."


class PlanModePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-plan-mode`: Mounts plan mode state machine and `exit_plan_mode` tool.
    """

    id = "plan-mode"
    name = "@deepseek-ai/dsh-plan-mode"
    inject = ["tools"]

    def apply(self, ctx: Any) -> None:
        cfg = self.config or {}
        section = cfg.get("section")
        controller = PlanModeController(ctx, section=section)
        ctx.set_service("plan_mode", controller)

        # 1. Register session projection if sessionProjections is mounted
        if ctx.has("sessionProjections"):
            projections = ctx.get("sessionProjections")
            if hasattr(projections, "register"):
                def apply_plan_projection(state: Any, event: Any) -> Any:
                    evt_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
                    evt_data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
                    current_active = state.get("active", False) if isinstance(state, dict) else False

                    if evt_type == "plan/mode":
                        new_active = bool(evt_data.get("active", False))
                        return {"active": new_active, "pending": False}
                    return state

                projections.register(
                    key="plan",
                    schema={"type": "object"},
                    init=lambda: {"active": False, "pending": False},
                    apply=apply_plan_projection,
                    view=lambda s: s,
                )

        # 2. Register /plan command if commands service is mounted
        if ctx.has("commands"):
            cmd_svc = ctx.get("commands")
            if hasattr(cmd_svc, "register"):
                def execute_plan_command(session: Any, args: List[str]) -> str:
                    sub = args[0].lower() if args else "on"
                    if sub in ("off", "stop", "exit", "0"):
                        res = controller.set_active(False, agent=None)
                        if res == "committed":
                            return "Plan mode off."
                        elif res == "queued":
                            return "Leaving plan mode (applies from the next step)."
                        else:
                            return "Plan mode is already inactive."
                    else:
                        res = controller.set_active(True, agent=None)
                        return "Plan mode on. Use /plan off to leave."

                cmd_svc.register(
                    name="plan",
                    description="Enter or leave plan mode",
                    handler=execute_plan_command,
                )

        # 3. Register exit_plan_mode tool
        tools = ctx.get("tools")
        parameters = {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "The complete plan, as markdown, starting with a # heading that names it.",
                }
            },
            "required": ["plan"],
        }

        if hasattr(tools, "register_tool"):
            disposer = tools.register_tool({
                "name": EXIT_PLAN_MODE,
                "description": EXIT_DESCRIPTION,
                "parameters": parameters,
                "execute": controller.handle_exit_plan_mode,
            })
        else:
            disposer = tools.register(
                name=EXIT_PLAN_MODE,
                description=EXIT_DESCRIPTION,
                parameters=parameters,
                handler=controller.handle_exit_plan_mode,
            )

        ctx.on("agent/prompt-assemble", controller.on_prompt_assemble)
        ctx.on("agent/pre-step", controller.on_pre_step)

        # Hook /plan command in agent pre-step if user types /plan in natural input
        ctx.on("agent/pre-step", self._hook_plan_slash_command)

        if hasattr(ctx, "effect"):
            ctx.effect(disposer)

    async def _hook_plan_slash_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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
            if text.startswith("/plan"):
                tokens = text.split(None, 1)
                controller: PlanModeController = self.ctx.get("plan_mode")
                if controller:
                    if len(tokens) == 1 or tokens[1].lower() in ("on", "start"):
                        controller.set_active(True)
                        last_user_msg["content"] += "\n\n[System Notice: Session switched to Plan Mode. Explore without modifying files, and call exit_plan_mode when ready.]"
                    elif tokens[1].lower() in ("off", "stop", "exit"):
                        controller.set_active(False)
                        last_user_msg["content"] += "\n\n[System Notice: Session switched back to Default Mode.]"
                    else:
                        controller.set_active(True)
                        last_user_msg["content"] = tokens[1] + "\n\n[System Notice: Session switched to Plan Mode.]"

        return payload
