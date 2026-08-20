from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin


class ToolSkillPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-tool-skill`: Model-facing `skill` loader tool and session skill catalog injection.
    """

    id = "tool-skill"
    name = "@deepseek-ai/dsh-tool-skill"
    inject = ["tools", "skills"]

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
                    "description": "The exact skill name from the available skills list."
                }
            },
            "required": ["name"]
        }

        tools_service.register(
            name="skill",
            description=description,
            parameters=parameters,
            handler=self.handle_load_skill
        )

        ctx.on("agent/prompt-assemble", self.on_prompt_assemble)
        ctx.on("agent/pre-step", self.on_pre_step)

    def handle_load_skill(self, name: str, ctx: Optional[Any] = None) -> str:
        if not ctx or not ctx.has("skills"):
            return "Error: Skills service unavailable"

        skills_service = ctx.get("skills")
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

        catalog_lines = ["\n\n<available_skills>"]
        for s in model_skills:
            desc = s.description
            if s.when_to_use:
                desc += f" (When to use: {s.when_to_use})"
            catalog_lines.append(f"- {s.name}: {desc}")
        catalog_lines.append("</available_skills>")

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
            if text.startswith("/"):
                first_token = text.split()[0][1:].lower()
                skills_service = self.ctx.get("skills")
                if skills_service:
                    skill = skills_service.get_skill(first_token)
                    if skill and skill.user_invocable:
                        skill_content = skill.render_content()
                        last_user_msg["content"] += f"\n\n[Injected Skill Instructions]\n{skill_content}"

        return payload
