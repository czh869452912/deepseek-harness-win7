import os
from typing import Any, Dict, List, Optional, Tuple
from dsh.cordis.plugin import Plugin
from dsh.skill.skill_service import parse_skill_file, SkillDefinition, SkillService


class FileSystemSkillProvider:
    """
    Local Filesystem Skill Provider scanning workspace and user home skill directories.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.custom_dirs: List[str] = self.config.get("customSkillDirs", [])

    def get_skill_roots(self, cwd: Optional[str] = None) -> List[Tuple[str, str, int]]:
        roots = []
        base_cwd = os.path.abspath(cwd or os.getcwd())

        roots.append((os.path.join(base_cwd, ".dsh", "skills"), "project-dsh", 100))
        roots.append((os.path.join(base_cwd, ".agents", "skills"), "project-agents", 200))
        roots.append((os.path.join(base_cwd, "skills"), "project-local", 250))

        for cd in self.custom_dirs:
            roots.append((os.path.abspath(cd), "custom", 300))

        home = os.path.expanduser("~")
        roots.append((os.path.join(home, ".dsh", "skills"), "user-dsh", 400))
        roots.append((os.path.join(home, ".agents", "skills"), "user-agents", 500))

        bundled_dir = self.config.get("bundledSkillDir") or os.environ.get("DSH_BUNDLED_SKILL_DIR")
        if bundled_dir and os.path.isdir(bundled_dir):
            roots.append((os.path.abspath(bundled_dir), "bundled", 600))

        return roots

    def discover_skills(self, cwd: Optional[str] = None) -> List[SkillDefinition]:
        discovered: List[SkillDefinition] = []
        roots = self.get_skill_roots(cwd=cwd)

        for root_path, source, rank in roots:
            if not os.path.isdir(root_path):
                continue

            try:
                for entry in os.listdir(root_path):
                    entry_path = os.path.join(root_path, entry)

                    if os.path.isdir(entry_path):
                        skill_md = os.path.join(entry_path, "SKILL.md")
                        if os.path.isfile(skill_md):
                            parsed = parse_skill_file(skill_md, default_name=entry, provider=source, rank=rank)
                            if parsed:
                                discovered.append(parsed)

                    elif os.path.isfile(entry_path) and entry.endswith(".md"):
                        skill_name = entry[:-3]
                        parsed = parse_skill_file(entry_path, default_name=skill_name, provider=source, rank=rank)
                        if parsed:
                            discovered.append(parsed)
            except Exception as e:
                print(f"[SkillFS Provider Warning] Exception scanning {root_path}: {e}")

        return discovered


class SkillFilesystemPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-skill-filesystem`: Scans local workspace & user roots for SKILL.md files.
    """

    id = "skill-filesystem"
    name = "@deepseek-ai/dsh-skill-filesystem"

    def apply(self, ctx: Any) -> None:
        if not ctx.has("skills"):
            ctx.set_service("skills", SkillService(ctx))

        provider = FileSystemSkillProvider(config=self.config)
        ctx.skills.add_provider(provider)
