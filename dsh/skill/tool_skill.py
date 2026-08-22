import hashlib
import re
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin


def digest_catalog_entries(entries: List[str]) -> str:
    combined = "\n".join(sorted(entries))
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


class ToolSkillPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-skill`: Model-facing `skill` loader tool and session skill catalog injection.
    """

    id = "tool-skill"
    name = "@deepseek-ai/dsh-tool-skill"
    inject = ["tools", "skills"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._last_catalog_hash: Optional[str] = None

    def apply(self, ctx: Any) -> None:
        tools_service = ctx.get("tools")
        if not tools_service:
            print("[ToolSkillPlugin Warning] tools service unavailable")
            return

        description = (
            "Load the full instructions for an available skill from the session skill catalog. "
            "Call this with the exact skill name from <available_skills> before acting on a task that names or clearly matches that skill."
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

        tools_service.register(
            name="skill",
            description=description,
            parameters=parameters,
            handler=self.handle_load_skill,
        )

        ctx.on("agent/prompt-assemble", self.on_prompt_assemble)
        ctx.on("agent/pre-step", self.on_pre_step)

    def handle_load_skill(self, name: str, ctx: Optional[Any] = None) -> str:
        context = ctx or self.ctx
        if not context or not context.has("skills"):
            return "Error: Skills service unavailable"

        skills_service = context.get("skills")
        skill = skills_service.get_skill(name)

        if not skill:
            return f"Error: Skill '{name}' is unknown or not available."

        if not skill.model_invocable:
            return f"Error: Skill '{name}' is not permitted for model invocation."

        return skill.render_content()

    def on_prompt_assemble(self, prompt: str) -> str:
        skills_service = self.ctx.get("skills")
        if not skills_service:
            return prompt

        skills = skills_service.list_skills()
        model_skills = [s for s in skills if s.model_invocable]

        if not model_skills:
            return prompt

        entries = []
        for s in model_skills:
            desc = s.description
            if s.when_to_use:
                desc += f" (When to use: {s.when_to_use})"
            entries.append(f"- {s.name}: {desc}")

        catalog_hash = digest_catalog_entries(entries)
        if catalog_hash == self._last_catalog_hash:
            return prompt

        self._last_catalog_hash = catalog_hash

        catalog_lines = ["\n\n<system-reminder>\n<available_skills>"]
        catalog_lines.extend(entries)
        catalog_lines.append("</available_skills>\n</system-reminder>")

        return prompt + "\n".join(catalog_lines)

    async def on_pre_step(self, payload: Dict[str, Any]) -> Dict[str, Any]:
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
            # Match /skill-name anywhere in user prompt
            matches = list(re.finditer(r"(?:^|\s)/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)", text, re.IGNORECASE))
            if matches:
                skills_service = self.ctx.get("skills")
                if skills_service:
                    for match in matches:
                        skill_name = match.group(1).lower()
                        skill = skills_service.get_skill(skill_name)
                        if skill and skill.user_invocable:
                            skill_content = skill.render_content()
                            if "[Injected Skill Instructions]" not in last_user_msg["content"]:
                                last_user_msg["content"] += f"\n\n[Injected Skill Instructions]\n{skill_content}"

        return payload
