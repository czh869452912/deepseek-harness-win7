import os
import re
from typing import Any, Dict, List, Optional, Tuple
import yaml

SKILL_NAME_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_valid_skill_name(name: str) -> bool:
    return bool(SKILL_NAME_REGEX.match(name))


class SkillDefinition:
    """
    Parsed Skill Definition containing metadata and markdown instruction body.
    """

    def __init__(
        self,
        name: str,
        description: str,
        content: str,
        when_to_use: Optional[str] = None,
        model_invocable: bool = True,
        user_invocable: bool = True,
        provider: str = "filesystem",
        resource_base: Optional[str] = None,
        path: Optional[str] = None,
        rank: int = 100
    ):
        self.name = name
        self.description = description
        self.content = content
        self.when_to_use = when_to_use
        self.model_invocable = model_invocable
        self.user_invocable = user_invocable
        self.provider = provider
        self.resource_base = resource_base
        self.path = path
        self.rank = rank

    def render_content(self) -> str:
        lines = [f'<skill_content name="{self.name}">', '<skill_resources>']
        if self.resource_base:
            lines.append(f'Base directory for this skill: {self.resource_base}')
            lines.append(
                'Resolve relative paths mentioned by this skill against the base directory before using them. Load referenced resources only as needed.'
            )
        else:
            lines.append(f'Resources for this skill are managed by provider "{self.provider}".')
        lines.extend([
            '</skill_resources>',
            '',
            '<skill_instructions>',
            self.content,
            '</skill_instructions>',
            '</skill_content>'
        ])
        return "\n".join(lines)


def parse_skill_file(filepath: str, default_name: str, provider: str = "filesystem", rank: int = 100) -> Optional[SkillDefinition]:
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()

        frontmatter = {}
        content = raw_text

        if raw_text.startswith("---"):
            parts = raw_text.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    content = parts[2].strip()
                except Exception as e:
                    print(f"[Skill Parse Error] Invalid frontmatter in {filepath}: {e}")

        name = str(frontmatter.get("name") or default_name).lower().strip()
        description = str(frontmatter.get("description") or f"Skill {name} instructions").strip()
        when_to_use = frontmatter.get("when_to_use") or frontmatter.get("whenToUse")
        model_invocable = not bool(frontmatter.get("disable-model-invocation", False))
        user_invocable = not bool(frontmatter.get("disable-user-invocation", False))

        resource_base = os.path.dirname(os.path.abspath(filepath))

        return SkillDefinition(
            name=name,
            description=description,
            content=content,
            when_to_use=when_to_use,
            model_invocable=model_invocable,
            user_invocable=user_invocable,
            provider=provider,
            resource_base=resource_base,
            path=os.path.abspath(filepath),
            rank=rank
        )
    except Exception as e:
        print(f"[Skill Parse Error] Failed to read {filepath}: {e}")
        return None


class SkillService:
    """
    Skill Registry Service mounted at `ctx.skills`.
    Manages skill discovery, registration, and catalog resolution.
    """

    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._registered_skills: Dict[str, SkillDefinition] = {}
        self._providers: List[Any] = []

    def register_skill(self, skill: SkillDefinition) -> None:
        self._registered_skills[skill.name] = skill

    def add_provider(self, provider: Any) -> None:
        self._providers.append(provider)

    def list_skills(self, cwd: Optional[str] = None) -> List[SkillDefinition]:
        skill_map: Dict[str, SkillDefinition] = dict(self._registered_skills)

        for provider in self._providers:
            if hasattr(provider, "discover_skills"):
                discovered = provider.discover_skills(cwd=cwd)
                for s in discovered:
                    if s.name not in skill_map or s.rank < skill_map[s.name].rank:
                        skill_map[s.name] = s

        return sorted(skill_map.values(), key=lambda s: s.name)

    def get_skill(self, name: str, cwd: Optional[str] = None) -> Optional[SkillDefinition]:
        skills = self.list_skills(cwd=cwd)
        for s in skills:
            if s.name == name:
                return s
        return None
