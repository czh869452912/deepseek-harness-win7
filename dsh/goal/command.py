"""Human /goal control, sharing the canonical goal domain and command registry."""
import re

from dsh.cordis.plugin import Plugin
from dsh.goal.service import GoalError
from dsh.goal.fold import goal_ref
from dsh.llm.message import create_user_message

USAGE = "Usage: /goal [<objective>|clear|edit <objective>|pause|resume]"


def render_goal(title, goal):
    if goal["phase"] == "active" and goal["activation"] == "armed":
        hint = "/goal edit <objective>, /goal pause, /goal clear"
    elif goal["phase"] == "complete":
        hint = "/goal <objective>, /goal clear"
    else:
        hint = "/goal edit <objective>, /goal resume, /goal clear"
    lines = [title, "Status: " + goal["phase"]]
    if goal["phase"] == "blocked":
        lines.append("Blocker: {code}: {message}".format(**goal["blockedReason"]))
    lines += ["Objective: " + goal["objective"], "Rounds: {}/{}".format(goal["roundsStarted"], goal["maxGoalRounds"]),
              "Activation: " + goal["activation"], "", "Commands: " + hint]
    return {"kind": "success", "text": "\n".join(lines)}


class CommandGoal(Plugin):
    id = "command-goal"
    inject = ["commands", "goals"]

    def apply(self, ctx):
        self.ctx = ctx
        ctx.get("commands").register({"name": "goal", "description": "set or view the goal for a long-running task",
            "input": {"hint": "[<objective>|clear|edit <objective>|pause|resume]", "images": True}, "handler": self.execute})

    def execute(self, invocation):
        raw, agent, attachments = invocation.rawInput.strip(), invocation.agent, invocation.attachments
        control = raw.lower()
        operation = control if control in ("clear", "pause", "resume") else "create"
        if not raw:
            operation = "show"
        elif control == "edit":
            operation = "invalid-edit"
        elif re.match(r"^edit\s", raw, re.IGNORECASE):
            operation, raw = "edit", raw[4:].strip()
        if attachments and operation not in ("create", "edit"):
            return {"kind": "error", "text": "Image attachments only accompany a goal objective: /goal <objective> or /goal edit <objective>."}
        goals = self.ctx.get("goals")
        try:
            current = goals.get(agent)
            if operation == "show":
                return render_goal("Goal", current) if current else {"kind": "success", "text": "No goal is currently set.\n" + USAGE}
            if operation == "invalid-edit":
                return {"kind": "error", "text": "Goal editing requires a replacement objective.\n" + USAGE}
            if operation == "clear":
                if current is None:
                    return {"kind": "success", "text": "No goal to clear."}
                goals.clear(agent, goal_ref(current))
                return {"kind": "success", "text": "Goal cleared."}
            if operation != "create" and current is None:
                return {"kind": "error", "text": "No goal is currently set; /goal {} requires one. {}".format(operation, USAGE)}
            if operation in ("pause", "resume"):
                return render_goal("Goal " + ("paused" if operation == "pause" else "resumed"), getattr(goals, operation)(agent, goal_ref(current)))
            if operation == "create" and current and current["phase"] != "complete":
                return {"kind": "error", "text": "A goal is already {}. Use /goal edit <objective> to change it or /goal clear before replacing it.".format(current["phase"])}
            create = operation == "create" or current["phase"] == "complete"
            goal = goals.create(agent, {"objective": raw}) if create else goals.edit(agent, goal_ref(current), {"objective": raw})
            if attachments:
                agent.followup(create_user_message({"content": list(attachments) + [{"type": "text", "text": "Reference images for the goal objective."}], "source": {"kind": "user"}}))
            return render_goal("Goal created" if create else "Goal updated", goal)
        except GoalError:
            return {"kind": "error", "text": "The goal command is not valid for the current state. Run /goal to view available commands."}
