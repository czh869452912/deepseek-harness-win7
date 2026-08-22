import os
import re
from typing import Any, Dict, List, Optional, Union

SKILL_NAME_REGEX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
BUNDLED_SKILL_RANK = 600
RUNTIME_RANK = 250


def is_skill_name(name: str) -> bool:
    """Return whether a string is a valid kebab-case skill name."""
    if not isinstance(name, str):
        return False
    return bool(SKILL_NAME_REGEX.match(name))


def is_valid_skill_name(name: str) -> bool:
    """Alias for is_skill_name."""
    return is_skill_name(name)


def escape_attr(value: str) -> str:
    return str(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def escape_text(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_resource_hint(provider: str, resource_base: Optional[Union[str, Dict[str, Any]]] = None) -> List[str]:
    if resource_base is None:
        return [
            f'Resources for this skill are managed by provider "{escape_text(provider)}".',
            'Load referenced resources only as needed.',
        ]

    if isinstance(resource_base, str):
        resource_base = {"kind": "directory", "path": resource_base}

    kind = resource_base.get("kind", "directory")
    if kind == "directory":
        path = resource_base.get("path", "")
        return [
            f'Base directory for this skill: {escape_text(path)}',
            'Resolve relative paths mentioned by this skill against the base directory before using them. Load referenced resources only as needed.',
        ]
    elif kind == "url":
        url = resource_base.get("url", "")
        return [
            f'Base URL for this skill: {escape_text(url)}',
            'Resolve relative URLs mentioned by this skill against the base URL before using them. Load referenced resources only as needed.',
        ]
    elif kind == "opaque":
        desc = resource_base.get("description", "")
        return [
            f'Resources for this skill: {escape_text(desc)}',
            'Load referenced resources only as needed.',
        ]
    else:
        return [
            f'Resources for this skill are managed by provider "{escape_text(provider)}".',
            'Load referenced resources only as needed.',
        ]


def render_skill_content(skill: Any) -> str:
    name = getattr(skill, "name", skill.get("name") if isinstance(skill, dict) else "")
    provider = getattr(skill, "provider", skill.get("provider") if isinstance(skill, dict) else "filesystem")
    resource_base = getattr(skill, "resource_base", skill.get("resource_base") if isinstance(skill, dict) else None)
    content = getattr(skill, "content", skill.get("content") if isinstance(skill, dict) else "")

    resource_hint = render_resource_hint(provider, resource_base)
    lines = [
        f'<skill_content name="{escape_attr(name)}">',
        '<skill_resources>',
    ]
    lines.extend(resource_hint)
    lines.extend([
        '</skill_resources>',
        '',
        '<skill_instructions>',
        content,
        '</skill_instructions>',
        '</skill_content>',
    ])
    return "\n".join(lines)


class SkillInvocationPolicy:
    def __init__(self, model_invocable: bool = True, user_invocable: bool = True):
        self.model_invocable = model_invocable
        self.user_invocable = user_invocable

    def to_dict(self) -> Dict[str, bool]:
        return {
            "modelInvocable": self.model_invocable,
            "userInvocable": self.user_invocable,
        }


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
        source: str = "custom",
        resource_base: Optional[Union[str, Dict[str, Any]]] = None,
        path: Optional[str] = None,
        rank: int = 100,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.description = description
        self.content = content
        self.when_to_use = when_to_use
        self.model_invocable = model_invocable
        self.user_invocable = user_invocable
        self.provider = provider
        self.source = source
        self.resource_base = (
            {"kind": "directory", "path": resource_base} if isinstance(resource_base, str) else resource_base
        )
        self.path = path
        self.rank = rank
        self.metadata = metadata or {}

    @property
    def invocation(self) -> SkillInvocationPolicy:
        return SkillInvocationPolicy(self.model_invocable, self.user_invocable)

    def render_content(self) -> str:
        return render_skill_content(self)


def parse_skill_file(
    filepath: str, default_name: str, provider: str = "filesystem", source: str = "custom", rank: int = 100
) -> Optional[SkillDefinition]:
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
                    import yaml
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    content = parts[2].strip()
                except Exception as e:
                    print(f"[Skill Parse Error] Invalid frontmatter in {filepath}: {e}")

        name = str(frontmatter.get("name") or default_name).lower().strip()
        description = str(frontmatter.get("description") or f"Skill {name} instructions").strip()
        when_to_use = frontmatter.get("when_to_use") or frontmatter.get("whenToUse")
        model_invocable = not bool(frontmatter.get("disable-model-invocation", False))
        user_invocable = not bool(frontmatter.get("disable-user-invocation", False))

        resource_base = {"kind": "directory", "path": os.path.dirname(os.path.abspath(filepath))}

        return SkillDefinition(
            name=name,
            description=description,
            content=content,
            when_to_use=when_to_use,
            model_invocable=model_invocable,
            user_invocable=user_invocable,
            provider=provider,
            source=source,
            resource_base=resource_base,
            path=os.path.abspath(filepath),
            rank=rank,
            metadata=frontmatter if isinstance(frontmatter, dict) else {},
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

    def register_provider(self, provider_factory: Any) -> None:
        if callable(provider_factory):
            class Control:
                signal = None

                def invalidate(self):
                    pass

            provider = provider_factory(Control())
            self._providers.append(provider)
        else:
            self._providers.append(provider_factory)

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
            elif hasattr(provider, "list"):
                # Call list(options)
                import asyncio
                opts = {"cwd": cwd}
                res = provider.list(opts)
                if asyncio.iscoroutine(res):
                    try:
                        res = asyncio.run(res)
                    except RuntimeError:
                        res = []
                if isinstance(res, dict) and "candidates" in res:
                    res = res["candidates"]
                if isinstance(res, list):
                    for c in res:
                        if isinstance(c, SkillDefinition):
                            s = c
                        else:
                            s = SkillDefinition(
                                name=c["name"],
                                description=c["description"],
                                content="",
                                when_to_use=c.get("whenToUse") or c.get("when_to_use"),
                                model_invocable=c.get("invocation", {}).get("modelInvocable", True) if isinstance(c.get("invocation"), dict) else getattr(getattr(c, "invocation", None), "model_invocable", True),
                                user_invocable=c.get("invocation", {}).get("userInvocable", True) if isinstance(c.get("invocation"), dict) else getattr(getattr(c, "invocation", None), "user_invocable", True),
                                provider=c.get("provider", "filesystem"),
                                source=c.get("source", "custom"),
                                resource_base=c.get("resourceBase") or c.get("resource_base"),
                                path=c.get("path"),
                                rank=c.get("rank", 100),
                            )
                        if s.name not in skill_map or s.rank < skill_map[s.name].rank:
                            skill_map[s.name] = s

        return sorted(skill_map.values(), key=lambda s: s.name)

    def list(self, options: Optional[Dict[str, Any]] = None) -> List[SkillDefinition]:
        cwd = options.get("cwd") if options else None
        return self.list_skills(cwd=cwd)

    def snapshot(self, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        skills = self.list(options)
        return {"skills": skills, "complete": True}

    def get_skill(self, name: str, cwd: Optional[str] = None) -> Optional[SkillDefinition]:
        if not is_skill_name(name):
            return None
        skills = self.list_skills(cwd=cwd)
        for s in skills:
            if s.name == name:
                return s
        return None

    def get(self, name: str, options: Optional[Dict[str, Any]] = None) -> Optional[SkillDefinition]:
        cwd = options.get("cwd") if options else None
        return self.get_skill(name, cwd=cwd)
