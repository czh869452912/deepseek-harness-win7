"""
AgentPresets service matching @deepseek-ai/dsh-agent-presets/index.ts.
Registry over the deployment's agent presets.
Python 3.8.10 compatible.
"""

import os
from typing import Any, Dict, List, Optional
from dsh.cordis.service import Service
from dsh.presets.authoring import copy_composition, delete_composition, read_composition
from dsh.presets.discovery import USER_PRESET_DIR, discover_presets
from dsh.presets.preset import (
    AgentPreset,
    Config,
    PresetMountError,
    PresetRoot,
    UnknownPresetError,
)
from dsh.presets.session import resolve_session_preset
from dsh.settings.types import settings_namespace


SETTINGS_NAMESPACE = "agent-presets"


class AgentPresets(Service):
    """
    Registry over the deployment's agent presets.
    Discovery is unmemoized: list() and resolve() re-read roots on every call.
    """

    name = "agentPresets"

    def __init__(self, ctx: Optional[Any] = None, config: Optional[Config] = None):
        if ctx is not None:
            super().__init__(ctx, name="agentPresets")
            self.ctx = ctx
        else:
            self.ctx = None

        shipped_root = os.path.join(os.getcwd(), "dsh", "presets")
        default_roots: List[PresetRoot] = []
        if os.path.isdir(shipped_root):
            default_roots.append(PresetRoot(path=shipped_root, trust="system"))

        if config is None:
            config = Config(default="standard", roots=default_roots, include_user_root=True)
        elif not config.roots:
            config.roots = default_roots

        self.config = config

        dsh_home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
        user_preset_path = os.path.join(dsh_home, USER_PRESET_DIR)

        if config.include_user_root:
            self.resolved_roots: List[PresetRoot] = list(config.roots) + [
                PresetRoot(path=user_preset_path, trust="user")
            ]
        else:
            self.resolved_roots = list(config.roots)

        self._settings_scope: Optional[Any] = None
        self._settings_service: Optional[Any] = None

        if self.ctx and hasattr(self.ctx, "inject"):
            def _mount_settings(sctx: Any):
                settings_svc = sctx.get("settings") if hasattr(sctx, "get") else getattr(sctx, "settings", None)
                if settings_svc:
                    try:
                        self._settings_scope = settings_svc.register(
                            settings_namespace(SETTINGS_NAMESPACE),
                            schema=None,
                            base={"default": config.default},
                        )
                        self._settings_service = settings_svc
                    except Exception:
                        pass
            self.ctx.inject(["settings"], _mount_settings)

        self._agent_preset_bindings: Dict[int, str] = {}

    @property
    def default_id(self) -> str:
        """The preset id mounted when a caller names none."""
        if self._settings_scope is not None:
            try:
                val = self._settings_scope.get()
                if isinstance(val, dict) and val.get("default"):
                    return str(val["default"])
            except Exception:
                pass
        return self.config.default

    @property
    def roots(self) -> List[PresetRoot]:
        """The roots discovery and authoring scan."""
        return self.resolved_roots

    @property
    def authorable(self) -> bool:
        """Whether this deployment has a root locally authored presets go to."""
        return any(r.trust == "user" for r in self.resolved_roots)

    async def list(self) -> List[AgentPreset]:
        """Every preset the configured roots currently supply."""
        return discover_presets(self.resolved_roots)

    async def resolve(self, id_str: Optional[str] = None) -> AgentPreset:
        """
        Resolve one preset by id (or defaultId if None).
        Throws UnknownPresetError if no configured root supplies that id.
        """
        wanted = id_str if id_str is not None else self.default_id
        presets = await self.list()
        for p in presets:
            if p.id == wanted:
                return p
        available = [p.id for p in presets]
        raise UnknownPresetError(wanted, available)

    async def resolve_mountable(self, id_str: Optional[str] = None) -> AgentPreset:
        """
        Resolve one preset that is about to compose an agent, refusing broken ones.
        """
        preset = await self.resolve(id_str)
        if preset.broken is not None:
            raise PresetMountError(preset.id, preset.broken)
        return preset

    async def read(self, id_str: str) -> str:
        """Read one preset's composition text."""
        preset = await self.resolve(id_str)
        return read_composition(preset)

    async def copy(self, from_id: str, id_str: str, name: Optional[str] = None) -> None:
        """Create a locally authored preset by copying an existing one whole."""
        source = await self.resolve(from_id)
        current = await self.list()
        if any(p.id == id_str for p in current):
            from dsh.presets.preset import PresetExistsError
            raise PresetExistsError(id_str)
        copy_composition(self.resolved_roots, source, id_str, name)

    async def remove(self, id_str: str) -> None:
        """Delete a locally authored preset."""
        preset = await self.resolve(id_str)
        delete_composition(self.resolved_roots, preset)

        if self._settings_scope is not None and self._settings_service is not None:
            try:
                curr_val = self._settings_scope.get()
                if isinstance(curr_val, dict) and curr_val.get("default") == id_str:
                    self._settings_service.mutate(
                        settings_namespace(SETTINGS_NAMESPACE),
                        [{"op": "unset", "path": ["default"]}]
                    )
            except Exception:
                pass

    def mount(self, agent_ctx: Any, id_str: Optional[str] = None) -> AgentPreset:
        """
        Compose one agent from a preset onto agent_ctx.
        """
        wanted = id_str if id_str is not None else self.default_id
        presets = discover_presets(self.resolved_roots)
        preset = next((p for p in presets if p.id == wanted), None)
        if preset is None:
            raise UnknownPresetError(wanted, [p.id for p in presets])
        if preset.broken is not None:
            raise PresetMountError(preset.id, preset.broken)

        self._agent_preset_bindings[id(agent_ctx)] = preset.id
        return preset

    def compose_from(self, agent_ctx: Any, parent_ctx: Any) -> Optional[str]:
        """Join agent_ctx to the same composition as parent_ctx."""
        pid = self._agent_preset_bindings.get(id(parent_ctx))
        if pid is not None:
            self._agent_preset_bindings[id(agent_ctx)] = pid
        return pid

    def composed_preset(self, agent_ctx: Any) -> Optional[str]:
        """The preset id one live agent runs on."""
        return self._agent_preset_bindings.get(id(agent_ctx))

    def recompose(self, agent_ctx: Any, id_str: str) -> AgentPreset:
        """Re-link agent_ctx to a different preset composition."""
        preset = self.mount(agent_ctx, id_str)
        return preset
