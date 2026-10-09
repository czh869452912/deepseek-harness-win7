"""
Plan Mode state machine (`@deepseek-ai/dsh-plan-mode`).
Provides logged per-agent collaboration state: while active, a deployment-owned guidance section
is included in each model request, and `exit_plan_mode` presents the completed plan for user review.
"""

import re
import weakref
from typing import Any, Dict, List, Optional

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.plugin import Plugin
from dsh.core.session import Session
from dsh.core.system_prompt.types import FIRST_PARTY_SECTION_ORDER
from dsh.interaction.user_questions import UserQuestionError
from dsh.llm.message import create_user_message

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


def resolve_config(config):
    section = config.get('section') if isinstance(config, dict) else None
    if not isinstance(section, str):
        raise ValueError('PlanModeConfig needs a string `section`')
    if not section.strip():
        raise ValueError('PlanModeConfig needs a non-empty `section`')
    unknown = [key for key in config if key != 'section']
    if unknown:
        raise ValueError('PlanModeConfig has unknown key(s) ' + ', '.join(unknown) + ' — config is { section }')
    return dict(section=section)


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


foldPlanMode = fold_plan_mode


def first_heading(plan: str) -> Optional[str]:
    """Find the first markdown heading in plan text."""
    for line in plan.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return None


def has_open_turn(events: List[Any]) -> bool:
    for ev in reversed(events):
        etype = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
        if etype == "turn/start":
            return True
        if etype == "turn/end":
            return False
    return False


class PlanModeController:
    """
    Plan Mode Service registered at `ctx.planMode`.
    Owns logged plan state, applies guidance during prompt assembly,
    and handles `exit_plan_mode` review transitions.
    """

    def __init__(self, ctx: Any, section: Optional[str] = None):
        self.ctx = ctx
        self.section = resolve_config(dict(section=section))["section"]
        self._pending_intents = weakref.WeakKeyDictionary()
        self._disposed = False
        def close():
            self._disposed = True
        ctx.effect(lambda: close, "plan service lifetime")

        ctx.get("systemPrompt").section({
            "name": "plan:policy",
            "order": FIRST_PARTY_SECTION_ORDER["PLAN_POLICY"],
            "text": lambda context: self.section if context.get("agent") is not None and self.is_active(context["agent"]) else "",
        })

    def _resolve_session(self, agent=None):
        return getattr(agent, "session", None)

    def is_active(self, agent: Optional[Any] = None) -> bool:
        sess = self._resolve_session(agent)
        if not sess:
            return False
        pending = self._pending_intents.get(sess)
        if pending is not None:
            return bool(pending.get("active", False))
        return fold_plan_mode(sess.events)

    def get(self, agent: Optional[Any] = None) -> Dict[str, Any]:
        sess = self._resolve_session(agent)
        if not sess:
            return {"active": False}
        active = fold_plan_mode(sess.events)
        pending = self._pending_intents.get(sess)
        if pending is not None:
            return {"active": active, "pending": pending.get("active", False)}
        return {"active": active}

    get_state = get

    def narration(self, session, target):
        last_header = next((i for i in range(len(session.events) - 1, -1, -1)
                            if session.events[i]["type"] == 'request/header'), None)
        if last_header is None or fold_plan_mode(session.events, last_header + 1) == target:
            return None
        text = 'The user switched this session to plan mode.' if target else 'The user switched this session back to the default mode.'
        return create_user_message(dict(content=[dict(type='text', text=text)],
            source=dict(kind='plugin', plugin='plan-mode', form='notice', summary=text)))

    def set(self, agent, active):
        session = self._resolve_session(agent)
        if session is None:
            return 'noop'
        pending = self._pending_intents.get(session)
        target = pending['active'] if pending else fold_plan_mode(session.events)
        if active == target:
            return 'noop'
        if has_open_turn(session.events):
            self._pending_intents[session] = dict(active=active, narrate=True)
            return 'cancelled' if fold_plan_mode(session.events) == active else 'queued'
        if active == fold_plan_mode(session.events):
            self._pending_intents.pop(session, None)
            return 'cancelled'
        session.append('plan/mode', dict(active=active))
        self._pending_intents.pop(session, None)
        narration = self.narration(session, active)
        if narration is not None:
            agent.inject(narration)
        return 'committed'

    def on_boundary(self, session):
        pending = self._pending_intents.get(session)
        if pending is None:
            return
        target = pending['active']
        if target != fold_plan_mode(session.events):
            session.append('plan/mode', dict(active=target))
        self._pending_intents.pop(session, None)

    async def on_pre_step(self, payload, next_fn=None):
        decision = await await_callback_result(next_fn()) if next_fn else payload
        agent, signal = payload.get('agent'), payload.get('signal')
        if agent is None or decision.get('kind') == 'reject' or getattr(signal, 'aborted', False):
            return decision
        pending = self._pending_intents.get(agent.session)
        if pending is None:
            return decision
        narration = self.narration(agent.session, pending['active'])
        try:
            self.on_boundary(agent.session)
        except Exception as error:
            self.ctx.logger.warn('dsh-plan-mode: failed to append selected plan mode at step start: %o', error)
            return decision
        if not pending['narrate'] or narration is None:
            return decision
        return dict(decision, messages=list(decision['messages']) + [narration])

    async def handle_exit_plan_mode(
        self,
        args: Optional[Dict[str, Any]] = None,
        plan: Optional[str] = None,
        agent: Optional[Any] = None,
        exec_input: Optional[Any] = None,
        ctx: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        """Execute exit_plan_mode tool call."""
        context = ctx or self.ctx
        effective_agent = agent or getattr(exec_input, "agent", None) or kwargs.get("agent")
        if effective_agent is None:
            raise RuntimeError("exit_plan_mode requires a calling agent (no session to switch)")

        if not fold_plan_mode(effective_agent.session.events):
            raise RuntimeError("exit_plan_mode is only available in plan mode")

        call_args = args if isinstance(args, dict) else kwargs
        plan_text = plan or (call_args.get("plan") if isinstance(call_args, dict) else "") or ""
        plan_clean = plan_text.strip()
        if not re.match(r"^#\s+\S", plan_clean):
            raise RuntimeError("exit_plan_mode requires a non-empty markdown plan starting with a # heading")

        uq_svc = context.get('userQuestions')
        if uq_svc is None:
            raise RuntimeError('no user-questions channel is available to review the plan; ask the user to switch the session mode instead')
        try:
            res = await uq_svc.ask(dict(agent=effective_agent,
                signal=getattr(exec_input, 'signal', None), questions=[dict(id=REVIEW_ID,
                    header='Plan review', question='Approve this plan and leave plan mode?', detail=plan_text,
                    options=[dict(label=APPROVE_LABEL, description='Leave plan mode; the plan is carried out from the next step.'),
                             dict(label=KEEP_PLANNING_LABEL, description='Stay in plan mode; feedback goes back to the model.')],
                    intent=dict(kind='plan-review', approve=APPROVE_LABEL))]))
        except UserQuestionError as error:
            if error.code == 'ASK_CANCELLED':
                raise RuntimeError('The user dismissed the plan review to speak instead; stay in plan mode, stop here, and wait for their message.') from error
            raise
        if self._disposed:
            raise RuntimeError("the plan-mode service was reloaded while the plan was under review; present the plan again")
        answers = [answer for answer in res['answers'] if answer['id'] == REVIEW_ID]
        item = answers[0] if len(answers) == 1 else None
        if item is None or item['selected'] != [APPROVE_LABEL] or 'custom' in item:
            feedback = item.get('custom', '') if item else ''
            raise RuntimeError('The user chose to keep planning; revise the plan and present it again.'
                if not feedback else 'The user chose to keep planning; their feedback: ' + feedback)
        self._pending_intents[effective_agent.session] = dict(active=False, narrate=False)
        return dict(approved=True)



class PlanModePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-plan-mode`: Mounts plan mode state machine and `exit_plan_mode` tool.
    """

    id = "plan-mode"
    name = "@deepseek-ai/dsh-plan-mode"
    inject = ["tools", "systemPrompt"]

    def apply(self, ctx: Any) -> None:
        cfg = self.config or {}
        section = resolve_config(cfg)["section"]
        controller = PlanModeController(ctx, section=section)
        ctx.set_service("planMode", controller)

        def mount_projection(pctx):
            def apply_projection(state, event):
                data = event["data"]
                if event["type"] == 'command/run' and data['name'] == 'plan':
                    if 'args' not in data:
                        return state
                    return dict(state, running=dict(commandId=data['commandId'], wanted=data['args'].strip() != 'off'))
                if event["type"] == 'command/done' and state['running'] is not None and data['commandId'] == state['running']['commandId']:
                    wanted = state['running']['wanted'] if data['kind'] == 'success' and state['running']['wanted'] != state['active'] else None
                    return dict(state, wanted=wanted, running=None)
                if event["type"] == 'plan/mode':
                    return dict(state, active=data['active'], wanted=None)
                return state
            def state_schema(value):
                if type(value) is not dict or set(value) != {'active', 'wanted', 'running'} or type(value.get('active')) is not bool or value.get('wanted') is not None and type(value['wanted']) is not bool:
                    raise ValueError('Invalid plan projection state')
                running = value.get('running')
                if running is not None and (type(running) is not dict or set(running) != {'commandId', 'wanted'} or type(running.get('commandId')) is not str or type(running.get('wanted')) is not bool):
                    raise ValueError('Invalid plan command projection')
                return dict(active=value['active'], wanted=value['wanted'], running=dict(running) if running is not None else None)
            def wire_view(state, header=None):
                wanted = state['running']['wanted'] if state['running'] is not None else state['wanted']
                return dict(active=state['active'], pending=wanted is not None and wanted != state['active'])
            def wire_schema(value):
                if type(value) is not dict or type(value.get('active')) is not bool or type(value.get('pending')) is not bool:
                    raise ValueError('Invalid plan projection')
                return dict(active=value['active'], pending=value['pending'])
            pctx.get('sessionProjections').register(dict(key='plan', stateSchema=state_schema,
                init=lambda header: dict(active=False, wanted=None, running=None), apply=apply_projection,
                wire=dict(view=wire_view, viewSchema=wire_schema), stateVersion=2))
        ctx.inject(['sessionProjections'], mount_projection)

        def mount_commands(command_ctx):
            cmd_svc = command_ctx.get("commands")
            def plan_command(invocation):
                agent = invocation.agent
                message = invocation.raw_input.strip()
                attachments = invocation.attachments
                if message == 'off' and attachments:
                    return dict(kind='error', text='Image attachments cannot accompany /plan off.')
                if message == 'off':
                    outcome = controller.set(agent, False)
                    texts = dict(committed='Plan mode off.',
                        queued='Leaving plan mode (applies from the next step).',
                        cancelled='Plan mode entry cancelled.')
                    text = texts.get(outcome, 'Leaving plan mode (applies from the next step).'
                        if fold_plan_mode(agent.session.events) else 'Plan mode is already inactive.')
                    return dict(kind='success', text=text)
                outcome = controller.set(agent, True)
                if message or attachments:
                    from dsh.llm.message import create_user_message
                    content = list(attachments) + ([dict(type='text', text=message)] if message else [])
                    agent.steer(create_user_message(dict(content=content, source=dict(kind='user'))))
                return dict(kind='success', text='Plan mode on. Use /plan off to leave.'
                    if outcome == 'committed' else 'Entering plan mode (applies from the next step). Use /plan off to leave.')

            cmd_svc.register(dict(name='plan', description='Enter or leave plan mode',
                input=dict(hint='[off|message]', images=True), handler=plan_command))

        ctx.inject(["commands"], mount_commands)

        # 3. Register exit_plan_mode tool
        tools = ctx.tools
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

        async def execute(args, execution):
            return await controller.handle_exit_plan_mode(args, exec_input=execution)
        disposer = tools.register(dict(name=EXIT_PLAN_MODE, description=EXIT_DESCRIPTION,
            parameters=parameters, execute=execute,
            output=dict(schema=dict(type='object', additionalProperties=False,
                properties=dict(approved=dict(type='boolean', const=True)), required=['approved']),
                render=lambda args, value: [dict(type='text', text='Plan approved — plan mode exited; carry out the plan starting with your next step.')]),
            presentCall=lambda args: dict(card='generic', title=first_heading(args['plan']) or 'Plan',
                kind='other', content=[dict(type='text', text=args['plan'])]),
            presentResult=lambda args, result: dict(card='generic', title='Plan review', content=result.content)))

        ctx.on("agent/pre-step", controller.on_pre_step)

        if hasattr(ctx, "disposable"):
            ctx.disposable(disposer, label="plan_mode.disposer")
        elif hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer)
