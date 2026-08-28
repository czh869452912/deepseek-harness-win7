import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.skill.skill_service import (
    escape_text,
    is_skill_name,
    render_skill_content,
)

DEFAULT_CATALOG_DESCRIPTION_MAX_LENGTH = 500
SKILL_GESTURE = re.compile(r"(?:^|\s)/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)", re.IGNORECASE)


def catalog_description(value: str, max_length: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length - 3]}..."


def digest_catalog_entries(entries: List[Dict[str, str]]) -> str:
    canonical = "\n".join(json.dumps([e["name"], e["description"]]) for e in entries)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_catalog_message(entries: List[Dict[str, str]]) -> str:
    lines = [
        "<system-reminder>",
        "A skill is a reusable set of task-specific instructions. The following skills are available in this session:",
        "",
        "<available_skills>",
    ]
    for entry in entries:
        lines.append(f"- `{entry['name']}`: {escape_text(entry['description'])}")
    lines.extend([
        "</available_skills>",
        "",
        "If the user names a skill, or the task clearly matches a skill's description, call the `skill` tool with the exact skill name before taking task actions. Load all applicable skills, then follow their full instructions. This catalog contains summaries only; do not infer or follow a skill's instructions until it has been loaded.",
        "A user may also invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool again for that skill.",
        "</system-reminder>",
    ])
    return "\n".join(lines)


def render_catalog_update(entries: List[Dict[str, str]]) -> str:
    lines = [
        "<system-reminder>",
        "The available skill catalog changed. This complete catalog replaces every earlier available-skills list in this session:",
        "",
        "<available_skills>",
    ]
    for entry in entries:
        lines.append(f"- `{entry['name']}`: {escape_text(entry['description'])}")
    lines.extend([
        "</available_skills>",
        "",
    ])
    if not entries:
        lines.extend([
            "No skills are currently available through the `skill` tool. Do not use names from earlier skill catalogs.",
            "A user may still invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool for it.",
        ])
    else:
        lines.extend([
            "Use only names in this replacement catalog. If the user names a listed skill, or the task clearly matches its description, call the `skill` tool with the exact name before acting.",
            "A user may also invoke a skill directly; its <skill_content> block then appears in this conversation. Follow it, and do not call the `skill` tool again for that skill.",
        ])
    lines.append("</system-reminder>")
    return "\n".join(lines)


class ToolSkillPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-skill`: Model-facing `skill` loader tool and session skill catalog injection.
    """

    id = "tool-skill"
    name = "@deepseek-ai/dsh-tool-skill"
    inject = ["tools", "skills"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.catalog_description_max_length = int(
            cfg.get("catalogDescriptionMaxLength", DEFAULT_CATALOG_DESCRIPTION_MAX_LENGTH)
        )
        self._last_catalog_hash: Optional[str] = None

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            if hasattr(ctx, "logger"):
                ctx.logger("tool-skill").warn("tools service unavailable")
            return

        description = (
            "Load the full instructions for an available skill. Call this with the exact skill name "
            "from the session skill catalog before acting on a task that names or clearly matches that skill."
        )

        parameters = {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The exact skill name from the available skills list.",
                }
            },
            "required": ["name"],
        }

        # Support both register and register_tool
        if hasattr(tools_service, "register_tool"):
            tools_service.register_tool({
                "name": "skill",
                "description": description,
                "parameters": parameters,
                "execute": self.handle_load_skill,
            })
        elif hasattr(tools_service, "register"):
            tools_service.register(
                name="skill",
                description=description,
                parameters=parameters,
                handler=self.handle_load_skill,
            )

        ctx.on("agent/prompt-assemble", self.on_prompt_assemble)
        ctx.on("agent/pre-step", self.on_pre_step)

    def handle_load_skill(self, name: str = "", ctx: Optional[Any] = None, **kwargs) -> str:
        context = ctx or self.ctx
        skill_name = name or kwargs.get("name", "")
        if not is_skill_name(skill_name):
            return f"Error: invalid skill name '{skill_name}'"

        if not context or not context.has("skills"):
            return "Error: Skills service unavailable"

        skills_service = context.get("skills")
        cwd = None
        if hasattr(context, "session") and getattr(context, "session", None):
            cwd = getattr(context.session.header, "cwd", None) if hasattr(context.session, "header") else None

        skill = skills_service.get_skill(skill_name, cwd=cwd)
        if not skill:
            return f"Error: skill '{skill_name}' is unknown or no longer available"

        if not skill.model_invocable:
            return f"Error: skill '{skill_name}' is not available for model invocation"

        return render_skill_content(skill)

    def on_prompt_assemble(self, prompt: str) -> str:
        skills_service = self.ctx.get("skills") if self.ctx else None
        if not skills_service:
            return prompt

        skills = skills_service.list_skills()
        model_skills = [s for s in skills if getattr(s, "model_invocable", True)]

        if not model_skills:
            return prompt

        entries = [
            {"name": s.name, "description": catalog_description(s.description, self.catalog_description_max_length)}
            for s in model_skills
        ]

        catalog_hash = digest_catalog_entries(entries)
        if catalog_hash == self._last_catalog_hash:
            return prompt

        self._last_catalog_hash = catalog_hash
        catalog_str = render_catalog_message(entries)
        return f"{prompt}\n\n{catalog_str}"

    async def on_pre_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        messages = payload.get("messages", [])
        if not messages:
            return payload

        skills_service = self.ctx.get("skills") if self.ctx else None
        if not skills_service:
            return payload

        # 1. Scan for user gesture invocation /name
        invoked_names: List[str] = []
        for msg in messages:
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
            source = msg.get("source", {}) if isinstance(msg, dict) else getattr(msg, "source", {})
            src_kind = source.get("kind") if isinstance(source, dict) else getattr(source, "kind", None)

            if role == "user" or src_kind == "user":
                content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text += " " + block.get("text", "")

                for match in SKILL_GESTURE.finditer(text):
                    sname = match.group(1).lower()
                    if sname not in invoked_names:
                        invoked_names.append(sname)

        # 2. Inject invoked skills instructions
        for sname in invoked_names:
            skill = skills_service.get_skill(sname)
            if skill and getattr(skill, "user_invocable", True):
                skill_content = render_skill_content(skill)
                # Find last user msg or append
                for msg in reversed(messages):
                    role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
                    if role == "user":
                        if isinstance(msg.get("content"), str):
                            if "[Injected Skill Instructions]" not in msg["content"]:
                                msg["content"] += f"\n\n[Injected Skill Instructions]\n{skill_content}"
                        break

        return payload
