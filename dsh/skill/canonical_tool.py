"""Durable, per-Agent skill catalogs and explicit skill instruction injection."""
import hashlib
import json
import re

from dsh.cordis.plugin import Plugin
from dsh.core.scope import scope_of
from dsh.llm.message import create_user_message
from dsh.skill.skill_service import is_skill_name, render_skill_content
from dsh.skill.tool_skill import catalog_description, render_catalog_message, render_catalog_update


GESTURE = re.compile(r"(?:^|\s)/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)")


def entries_of(message):
    source = message.get("source", {})
    entries = source.get("entries")
    if source.get("kind") != "skill-catalog" or not isinstance(entries, list):
        return None
    if any(not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"] or not isinstance(row.get("description"), str) for row in entries):
        return None
    return [{"name": row["name"], "description": row["description"]} for row in entries]


def digest(entries):
    wire = "\n".join(json.dumps([row["name"], row["description"]], ensure_ascii=False, separators=(",", ":")) for row in entries)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def lookup(agent, signal):
    return {"cwd": agent.session.header.cwd if agent is not None else None,
            "signal": signal if signal is not None else getattr(agent, "_cancel_event", None),
            "scope": scope_of(agent.ctx) if agent is not None else None}


def allowed(skill, field):
    return skill.get("invocation", {}).get(field, True)


class CanonicalToolSkill(Plugin):
    id = "tool-skill"
    inject = ["agents", "tools", "skills"]

    def apply(self, ctx):
        maximum = self.config.get("catalogDescriptionMaxLength", 500)
        if type(maximum) is not int or maximum < 3:
            raise ValueError("catalogDescriptionMaxLength must be an integer >= 3")
        skills, tools = ctx.get("skills"), ctx.get("tools")
        async def execute(args, execution):
            name = args["name"]
            if not is_skill_name(name):
                raise ValueError("invalid skill name {!r}".format(name))
            options = lookup(execution.agent, execution.signal)
            summary = next((row for row in await skills.list(options) if row["name"] == name), None)
            if summary is None:
                raise ValueError("skill {!r} is unknown or no longer available".format(name))
            if not allowed(summary, "modelInvocable"):
                raise ValueError("skill {!r} is not available for model invocation".format(name))
            skill = await skills.get(name, options)
            if skill is None or not allowed(skill, "modelInvocable"):
                raise ValueError("skill {!r} is no longer available for model invocation".format(name))
            return {key: skill[key] for key in ("name", "provider", "resourceBase", "content") if key in skill}
        resource_variants = []
        for kind, field in (("directory", "path"), ("url", "url"), ("opaque", "description")):
            resource_variants.append({"type": "object", "additionalProperties": False,
                "properties": {"kind": {"type": "string", "const": kind}, field: {"type": "string"}}, "required": ["kind", field]})
        definition = {"name": "skill", "description": "Load the full instructions for an available skill. Call this with the exact skill name from the session skill catalog before acting on a task that names or clearly matches that skill.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            "execute": execute, "output": {"schema": {"type": "object", "additionalProperties": False,
                "properties": dict({key: {"type": "string"} for key in ("name", "provider", "content")}, resourceBase={"oneOf": resource_variants}),
                "required": ["name", "provider", "content"]},
                "render": lambda _args, value: [{"type": "text", "text": render_skill_content(value)}]}}
        tools.register(definition)
        # ToolsService normalizes dictionaries once; remember the exact registered
        # object so a same-name scoped shadow does not inherit this guidance.
        own_tool = tools.get("skill", scope_of(ctx))

        async def invocation(payload, next_fn):
            decision = await next_fn()
            if decision.get("kind") == "reject":
                return decision
            names = []
            for message in payload["messages"]:
                if message.get("source", {}).get("kind") != "user":
                    continue
                for block in message.get("content", []):
                    if block.get("type") == "text":
                        for name in GESTURE.findall(block["text"]):
                            if name not in names:
                                names.append(name)
            injections = []
            for name in names:
                skill = await skills.get(name, lookup(payload["agent"], payload.get("signal")))
                if skill is not None and allowed(skill, "userInvocable"):
                    injections.append(create_user_message({"content": [{"type": "text", "text": render_skill_content(skill)}],
                        "source": {"kind": "skill-invocation", "name": name, "form": "instructions"}}))
            return dict(decision, messages=decision["messages"] + injections) if injections else decision

        async def catalog(payload, next_fn):
            decision = await next_fn()
            if decision.get("kind") == "reject":
                return decision
            agent = payload["agent"]
            snapshot = await skills.snapshot(lookup(agent, payload.get("signal"))) if tools.get("skill", scope_of(agent.ctx)) is own_tool else {"skills": [], "complete": True}
            if not snapshot["complete"]:
                return decision
            entries = [{"name": row["name"], "description": catalog_description(row["description"], maximum)} for row in snapshot["skills"] if allowed(row, "modelInvocable")]
            current_digest, published, visible_digest = digest(entries), False, None
            surface = agent.session.surface
            visible = set(surface.nodes)
            for event in reversed(agent.session.events):
                old = entries_of(event.get("data", {})) if event.get("type") == "user/message" else None
                if old is not None:
                    published = True
                    if event["seq"] in visible:
                        visible_digest = digest(old)
                        break
            existing = next((message for message in decision["messages"] if entries_of(message) is not None), None)
            if visible_digest == current_digest or not published and not entries:
                return dict(decision, messages=[message for message in decision["messages"] if message is not existing]) if existing else decision
            if existing is not None and digest(entries_of(existing)) == current_digest:
                return decision
            source = {"kind": "skill-catalog", "form": "catalog", "entries": entries}
            if published:
                source["update"] = True
            message = create_user_message({"source": source, "content": [{"type": "text", "text": (render_catalog_update if published else render_catalog_message)(entries)}]})
            return dict(decision, messages=[message if item is existing else item for item in decision["messages"]] if existing else decision["messages"] + [message])

        ctx.on("agent/pre-step", invocation)
        ctx.on("agent/pre-step", catalog)
