"""Model goal controls authenticated against the live driver's admitted turn."""
import json

from dsh.cordis.plugin import Plugin
from dsh.goal.fold import integer
from dsh.goal.service import GoalError
from dsh.llm.message import create_user_message


def execution_window(ctx, execution):
    agent = getattr(execution, "agent", None)
    if agent is None:
        raise GoalError("goal tools require a calling agent", "GOAL_TOOL_AGENT_REQUIRED")
    agents = ctx.get("agents")
    if agents.get(agent.id) is not agent or agent.status != "running" or agents.current_initiator() is not agent:
        raise GoalError("goal tools require the exact live calling agent inside its active driver", "GOAL_TOOL_DRIVER_REQUIRED")
    events = agent.session.events
    for index in range(len(events) - 1, -1, -1):
        if events[index]["type"] == "turn/end":
            break
        if events[index]["type"] == "turn/start":
            return agent, events[index + 1:]
    raise GoalError("goal tools require an open model turn", "GOAL_TOOL_DRIVER_REQUIRED")


def direct_human(ctx, agent, events):
    return agent in ctx.get("agents").roots() and any(event["type"] == "user/message" and event["data"]["source"]["kind"] == "user" for event in events)


def require_human(ctx, agent, events):
    if not direct_human(ctx, agent, events):
        raise GoalError("this goal operation requires a direct human turn on a top-level agent", "GOAL_TOOL_AUTHORITY_REQUIRED")


def completion_authority(ctx, agent, events):
    if direct_human(ctx, agent, events):
        return None
    goal = ctx.get("goals").get(agent)
    if goal:
        for event in events:
            source = event["data"].get("source", {}) if event["type"] == "user/message" else {}
            if (source.get("kind") == "goal" and source.get("goalId") == goal["id"] and
                    source.get("revision") == goal["revision"] and source.get("round") == goal["roundsStarted"]):
                return goal
    raise GoalError("complete and blocked require a direct human turn or the current goal round", "GOAL_TOOL_AUTHORITY_REQUIRED")


def goal_value(goal):
    if goal is None:
        return {"goal": None}
    keys = ("id", "revision", "objective", "phase", "roundsStarted", "maxGoalRounds", "blockedReason")
    return {"goal": {key: goal[key] for key in keys if key in goal}, "activation": goal["activation"]}


def render_wrapup(objective, reason=None):
    heading = "Objective: " + json.dumps(objective, ensure_ascii=False) + "\n"
    grounding = "Report only what earlier rounds and tool results in this session actually establish; when a detail is not in the session, say so instead of inventing it. "
    if reason is None:
        text = ('<goal_complete>\n' + heading + 'The goal is marked complete and this autonomous run is ending. Write the closing '
            + 'message to the user now: state the outcome, summarize what was done and how it was '
            + 'verified, and point to the concrete results (files, commits, or other artifacts). ' + grounding
            + 'Note anything the user should review or do next. Address the user directly. Do not '
            + "call any more tools in this run; further work waits for the user's next instruction.\n</goal_complete>")
    else:
        text = ('<goal_blocked>\n' + heading + 'Blocked: ' + json.dumps(reason, ensure_ascii=False) + '\n'
            + 'The goal is marked blocked and this autonomous run is ending. Write the closing '
            + 'message to the user now: state what has been completed so far, describe the concrete '
            + 'blocking condition and what you tried, and say exactly what you need from the user to '
            + 'continue. ' + grounding + 'Address the user directly. Do not call any more tools in this run; further work '
            + "waits for the user's next instruction.\n</goal_blocked>")
    return [{"type": "text", "text": text}]


def summary(text):
    wire = text.encode("utf-16-le", "surrogatepass")
    return text if len(wire) <= 240 else wire[:238].decode("utf-16-le", "surrogatepass") + "…"


def output_schema():
    fields = {key: {"type": "string"} for key in ("id", "objective", "phase")}
    fields.update({key: {"type": "integer"} for key in ("revision", "roundsStarted", "maxGoalRounds")})
    fields["phase"]["enum"] = ["active", "paused", "blocked", "complete"]
    fields["blockedReason"] = {"type": "object", "additionalProperties": False, "required": ["code", "message"],
                               "properties": {"code": {"type": "string"}, "message": {"type": "string"}}}
    return {"oneOf": [
        {"type": "object", "additionalProperties": False, "required": ["goal"], "properties": {"goal": {"type": "null"}}},
        {"type": "object", "additionalProperties": False, "required": ["goal", "activation"], "properties": {
            "goal": {"type": "object", "additionalProperties": False, "properties": fields,
                     "required": [key for key in fields if key != "blockedReason"]},
            "activation": {"type": "string", "enum": ["armed", "disarmed"]}}}]}


def present_call(name, args):
    if name == "get_goal":
        return {"card": "generic", "title": "Read current goal", "kind": "read"}
    if name == "create_goal":
        return {"card": "generic", "title": "Create goal", "kind": "other", "rawInput": args["objective"]}
    action = args["action"]
    raw = args.get("blocked_reason") or args.get("objective") or args.get("max_goal_rounds") or args["goal_id"]
    return {"card": "generic", "title": ("Mark" if action == "blocked" else action.capitalize()) + " goal", "kind": "other", "rawInput": raw}


class CanonicalToolGoal(Plugin):
    id = "tool-goal"
    inject = ["agents", "goals", "tools", "systemPrompt"]

    def apply(self, ctx):
        self.ctx = ctx
        self.threshold = integer(self.config.get("blockedAfterConsecutiveRounds", 3), 1)
        ctx.get("systemPrompt").section({"name": "tool:goal", "order": 2400, "text":
            'Use goal tools for one long-running completion objective in the current session. '
            'create_goal may infer goal intent from a direct human request in any language; do not '
            'create a goal for routine single-turn work. Call get_goal before update_goal and copy its '
            'exact goal_id and revision. After session resume or fork, an active goal is disarmed: when '
            'a human asks to continue or resume in any wording or language, use update_goal action '
            'resume to rearm it. Mark complete only when the objective is actually achieved. Mark '
            'blocked only after the same blocking condition persists for at least {} '.format(self.threshold)
            + 'consecutive goal rounds, and report that concrete condition in blocked_reason; difficulty, uncertainty, '
            + 'or useful remaining work is not blocked.'})
        definitions = [
            ("get_goal", "Read the current same-session goal, including its exact id/revision, objective, phase, completed continuation rounds, round limit, blocker reason when present, and whether another continuation is armed. Call this before updating a goal.", {}, [], self.get),
            ("create_goal", 'Create one persisted same-session completion goal when the current direct human request is a long-running objective that should continue across autonomous goal rounds. You may infer that intent without requiring the user to say "create a goal". Do not use this for trivial single-turn work. Execution rejects non-human and subagent authority.',
             {"objective": {"type": "string", "description": "The concrete completion objective inferred from the direct human request."},
              "max_goal_rounds": {"type": "number", "description": "Optional positive safe-integer limit on automatic continuation rounds."}}, ["objective"], self.create),
            ("update_goal", 'Update the exact current goal revision. edit, pause, and resume require a direct top-level human request. During an automatic continuation of the current goal, complete and blocked are also allowed. blocked is rejected before the configured minimum round count; the model remains responsible for judging that the same condition persisted across those rounds and must explain it in blocked_reason.',
             {"goal_id": {"type": "string", "description": "Exact id returned by get_goal."},
              "revision": {"type": "number", "description": "Exact positive revision returned by get_goal."},
              "action": {"type": "string", "enum": ["edit", "pause", "resume", "complete", "blocked"], "description": "edit | pause | resume | complete | blocked"},
              "objective": {"type": "string", "description": "Replacement objective; valid only with action edit."},
              "max_goal_rounds": {"type": "number", "description": "Replacement cap; valid only with action edit."},
              "blocked_reason": {"type": "string", "description": "Concrete blocking condition; required only with action blocked."}}, ["goal_id", "revision", "action"], self.update)]
        for name, description, properties, required, execute in definitions:
            ctx.get("tools").register({"name": name, "description": description,
                "parameters": dict(type="object", properties=properties, **({"required": required} if required else {})), "execute": execute,
                "presentCall": lambda args, tool_name=name: present_call(tool_name, args),
                "output": {"schema": output_schema(), "render": lambda args, value: [{"type": "text", "text": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}]}})

    async def get(self, args, execution):
        agent, _ = execution_window(self.ctx, execution)
        return goal_value(self.ctx.get("goals").get(agent))

    async def create(self, args, execution):
        agent, events = execution_window(self.ctx, execution)
        require_human(self.ctx, agent, events)
        request = {"objective": args["objective"]}
        if "max_goal_rounds" in args:
            request["maxGoalRounds"] = args["max_goal_rounds"]
        return goal_value(self.ctx.get("goals").create(agent, request))

    async def update(self, args, execution):
        agent, events = execution_window(self.ctx, execution)
        def invalid(message):
            raise GoalError(message, "GOAL_TOOL_INVALID_UPDATE")
        key, revision, action = args["goal_id"], args["revision"], args["action"]
        if not isinstance(key, str) or not key or key != key.strip():
            invalid("goal_id must be non-empty and normalized")
        try:
            integer(revision, 1)
        except ValueError:
            invalid("revision must be a positive safe integer")
        ref, goals = {"id": key, "revision": revision}, self.ctx.get("goals")
        replacements = {}
        if args.get("objective", "") != "":
            replacements["objective"] = args["objective"]
        if args.get("max_goal_rounds", 0) != 0:
            replacements["maxGoalRounds"] = args["max_goal_rounds"]
        reason = args.get("blocked_reason", "")
        if action in ("edit", "pause", "resume"):
            require_human(self.ctx, agent, events)
            if reason or (action != "edit" and replacements):
                invalid("replacement fields are valid only with edit; blocked_reason only with blocked")
            goal = goals.edit(agent, ref, replacements) if action == "edit" else getattr(goals, action)(agent, ref)
            return goal_value(goal)
        if action not in ("complete", "blocked"):
            invalid("invalid goal action")
        authority = completion_authority(self.ctx, agent, events)
        if replacements or action == "complete" and reason:
            invalid("unexpected replacement fields or blocked_reason")
        if action == "blocked":
            if not isinstance(reason, str) or not reason.strip():
                invalid("blocked_reason is required with action blocked")
            if authority and authority["roundsStarted"] < self.threshold:
                raise GoalError("blocked requires at least {} consecutive goal rounds; current round is {}".format(self.threshold, authority["roundsStarted"]), "GOAL_TOOL_BLOCK_THRESHOLD")
        goal = goals.complete(agent, ref) if action == "complete" else goals.block(agent, ref, {"code": "model-reported", "message": reason})
        if authority:
            execution.deferContext(create_user_message({"content": render_wrapup(goal["objective"], reason if action == "blocked" else None),
                "source": {"kind": "plugin", "plugin": "tool-goal", "form": "notice", "summary": summary(action + ": " + goal["objective"])}}))
        return goal_value(goal)
