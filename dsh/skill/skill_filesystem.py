import os
from typing import Any, Dict, List, Optional, Tuple
from dsh.cordis.plugin import Plugin
from dsh.skill.skill_service import parse_skill_file, SkillDefinition, SkillService, BUNDLED_SKILL_RANK


class FileSystemSkillProvider:
    """
    Local Filesystem Skill Provider scanning workspace and user home skill directories.
    Matches @deepseek-ai/dsh-skill-filesystem specification.
    """

    def __init__(self, ctx: Any = None, control: Any = None, config: Optional[Dict[str, Any]] = None):
        self.ctx = ctx
        self.config = config or {}
        self.name = self.config.get("providerName", "filesystem")
        self.include_default_roots = self.config.get("includeDefaultRoots", True)
        self.custom_dirs: List[str] = [os.path.abspath(d) for d in self.config.get("customSkillDirs", [])]

    def get_skill_roots(self, cwd: Optional[str] = None) -> List[Tuple[str, str, int]]:
        roots: List[Tuple[str, str, int]] = []

        if self.include_default_roots and cwd is not None:
            base_cwd = os.path.abspath(cwd)
            roots.append((os.path.join(base_cwd, ".dsh", "skills"), "project-dsh", 100))
            roots.append((os.path.join(base_cwd, ".agents", "skills"), "project-agents", 200))

        for cd in self.custom_dirs:
            roots.append((cd, "custom", 300))

        if self.include_default_roots:
            home = os.path.expanduser("~")
            dsh_home = self.config.get("dshHome") or os.environ.get("DSH_HOME") or os.path.join(home, ".dsh")
            agents_home = self.config.get("agentsHome") or os.environ.get("DSH_AGENTS_HOME") or os.path.join(home, ".agents")

            roots.append((os.path.join(dsh_home, "skills"), "user-dsh", 400))
            roots.append((os.path.join(agents_home, "skills"), "user-agents", 500))

        bundled_dir = self.config.get("bundledSkillDir") or os.environ.get("DSH_BUNDLED_SKILL_DIR")
        if bundled_dir and os.path.isdir(bundled_dir):
            roots.append((os.path.abspath(bundled_dir), "bundled", BUNDLED_SKILL_RANK))

        return roots

    def discover_skills(self, cwd: Optional[str] = None) -> List[SkillDefinition]:
        discovered: List[SkillDefinition] = []
        roots = self.get_skill_roots(cwd=cwd)

        for root_path, source, rank in roots:
            if not os.path.isdir(root_path):
                continue

            try:
                entries = sorted(os.listdir(root_path))
                for entry in entries:
                    if entry == ".system":
                        continue
                    entry_path = os.path.join(root_path, entry)

                    if os.path.isdir(entry_path):
                        skill_md = os.path.join(entry_path, "SKILL.md")
                        if os.path.isfile(skill_md):
                            parsed = parse_skill_file(
                                skill_md,
                                default_name=entry,
                                provider=self.name,
                                source=source,
                                rank=rank,
                            )
                            if parsed:
                                discovered.append(parsed)

                    elif os.path.isfile(entry_path) and entry.endswith(".md"):
                        skill_name = entry[:-3]
                        parsed = parse_skill_file(
                            entry_path,
                            default_name=skill_name,
                            provider=self.name,
                            source=source,
                            rank=rank,
                        )
                        if parsed:
                            discovered.append(parsed)
            except Exception as e:
                print(f"[SkillFS Provider Warning] Exception scanning {root_path}: {e}")

        return discovered

    async def list(self, options: Optional[Dict[str, Any]] = None) -> List[SkillDefinition]:
        cwd = options.get("cwd") if options else None
        return self.discover_skills(cwd=cwd)

    async def get(self, candidate: Any, options: Optional[Dict[str, Any]] = None) -> Optional[SkillDefinition]:
        path = candidate.path if hasattr(candidate, "path") else candidate.get("path")
        if not path or not os.path.isfile(path):
            return None
        name = candidate.name if hasattr(candidate, "name") else candidate.get("name", "skill")
        provider = candidate.provider if hasattr(candidate, "provider") else candidate.get("provider", self.name)
        source = candidate.source if hasattr(candidate, "source") else candidate.get("source", "custom")
        rank = candidate.rank if hasattr(candidate, "rank") else candidate.get("rank", 100)
        return parse_skill_file(path, default_name=name, provider=provider, source=source, rank=rank)


class SkillFilesystemPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-skill-filesystem`: Scans local workspace & user roots for SKILL.md files.
    """

    id = "skill-filesystem"
    name = "@deepseek-ai/dsh-skill-filesystem"

    def apply(self, ctx: Any) -> None:
        if not ctx.has("skills"):
            ctx.set_service("skills", SkillService(ctx))

        provider = FileSystemSkillProvider(ctx=ctx, config=self.config)
        ctx.skills.add_provider(provider)
