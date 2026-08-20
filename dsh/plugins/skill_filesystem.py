import os
from typing import Any, Dict, List, Optional, Tuple
from dsh.cordis.plugin import Plugin
from dsh.services.skills import parse_skill_file, SkillDefinition, SkillService


class FileSystemSkillProvider:
    """
    Local Filesystem Skill Provider scanning workspace and user home skill directories.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.custom_dirs: List[str] = self.config.get("customSkillDirs", [])

    def get_skill_roots(self, cwd: Optional[str] = None) -> List[Tuple[str, str, int]]:
        """
        Returns list of tuples: (root_dir_path, source_name, rank_number)
        Lower rank wins duplicate skill names.
        """
        roots = []
        base_cwd = os.path.abspath(cwd or os.getcwd())

        # 1. Project roots (rank 100-200)
        roots.append((os.path.join(base_cwd, ".dsh", "skills"), "project-dsh", 100))
        roots.append((os.path.join(base_cwd, ".agents", "skills"), "project-agents", 200))
        roots.append((os.path.join(base_cwd, "skills"), "project-local", 250))

        # 2. Custom skill dirs (rank 300)
        for cd in self.custom_dirs:
            roots.append((os.path.abspath(cd), "custom", 300))

        # 3. User home roots (rank 400-500)
        home = os.path.expanduser("~")
        roots.append((os.path.join(home, ".dsh", "skills"), "user-dsh", 400))
        roots.append((os.path.join(home, ".agents", "skills"), "user-agents", 500))

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

                    # Directory bundle skill (e.g. skills/my-skill/SKILL.md)
                    if os.path.isdir(entry_path):
                        skill_md = os.path.join(entry_path, "SKILL.md")
                        if os.path.isfile(skill_md):
                            parsed = parse_skill_file(skill_md, default_name=entry, provider=source, rank=rank)
                            if parsed:
                                discovered.append(parsed)

                    # Flat Markdown skill file (e.g. skills/my-skill.md)
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
