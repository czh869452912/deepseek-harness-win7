"""Agent preset roster and standing per-session composition service."""

import asyncio
import inspect
import os
import weakref
from typing import Any, Dict, List, Optional, Tuple

from dsh.cordis.service import Service
from dsh.presets.authoring import copy_composition, delete_composition, read_composition
from dsh.presets.discovery import USER_PRESET_DIR, discover_presets
from dsh.presets.mount import mount_preset, service_for_agent
from dsh.presets.preset import (
    AgentPreset, Config as PresetConfig, PresetExistsError, PresetMountError,
    PresetRoot, UnknownPresetError,
)
from dsh.settings.types import settings_namespace


SETTINGS_NAMESPACE = "agent-presets"


class _ConfigSchema:
    def validate(self, value: Any) -> Dict[str, Any]:
        issues = []
        if not isinstance(value, dict):
            return {"value": value, "issues": [{"message": "expected an object"}]}
        if not isinstance(value.get("default"), str):
            issues.append({"message": "expected a required string", "path": ["default"]})
        roots = value.get("roots", [])
        if not isinstance(roots, list):
            issues.append({"message": "expected an array", "path": ["roots"]})
            roots = []
        else:
            for index, root in enumerate(roots):
                if not isinstance(root, dict) or not isinstance(root.get("path"), str):
                    issues.append({"message": "expected a path string", "path": ["roots", index]})
                elif root.get("trust", "user") not in ("system", "user"):
                    issues.append({"message": "expected system or user", "path": ["roots", index, "trust"]})
        include = value.get("includeUserRoot", value.get("include_user_root", True))
        if not isinstance(include, bool):
            issues.append({"message": "expected a boolean", "path": ["includeUserRoot"]})
        parsed = dict(value)
        parsed["roots"] = roots
        parsed["includeUserRoot"] = include
        return {"value": parsed, "issues": issues}


class _SettingsSchema:
    def __call__(self, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise TypeError("agent-presets settings must be an object")
        if value.get("default") is not None and not isinstance(value.get("default"), str):
            raise TypeError("agent-presets default must be a string")
        return value

    def to_json(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"default": {"type": "string"}}}


AGENT_PRESET_SETTINGS_SCHEMA = _SettingsSchema()


def _config_value(config: Any) -> Tuple[str, List[PresetRoot], bool]:
    if config is None:
        return "standard", [], True
    if isinstance(config, PresetConfig):
        return config.default, list(config.roots), config.include_user_root
    roots = []
    for root in config.get("roots", []):
        roots.append(root if isinstance(root, PresetRoot) else PresetRoot(root["path"], root.get("trust", "user")))
    include = config.get("includeUserRoot", config.get("include_user_root", True))
    return config["default"], roots, include


def _stamp(path: str) -> Optional[Tuple[int, int]]:
    try:
        stat = os.stat(path)
        stamp = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000))
        return int(stamp), stat.st_size
    except OSError:
        return None


class _Standing:
    def __init__(self, mount: Any, stamp: Tuple[int, int]):
        self.mount = mount
        self.key = mount.key
        self.stamp = stamp


class AgentPresets(Service):
    inject = ["loader"]
    Config = _ConfigSchema()
    name = "agentPresets"

    def __init__(self, ctx: Any, config: Any = None):
        super().__init__(ctx, "agentPresets")
        self.self_ctx = ctx
        default, roots, include_user_root = _config_value(config)
        self.config = PresetConfig(default, roots, include_user_root)
        dsh_home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
        self.resolved_roots = list(roots)
        if include_user_root:
            self.resolved_roots.append(PresetRoot(os.path.join(dsh_home, USER_PRESET_DIR), "user"))
        self._settings_scope = None
        self._settings_service = None
        self._standing: Dict[str, asyncio.Future] = {}
        self._bindings = weakref.WeakKeyDictionary()

        def mount_settings(settings_ctx: Any) -> None:
            settings = settings_ctx.get("settings")
            scope = settings.register(
                settings_namespace(SETTINGS_NAMESPACE), AGENT_PRESET_SETTINGS_SCHEMA,
                base={"default": default},
            )
            self._settings_scope = scope
            self._settings_service = settings

            def cleanup() -> None:
                if self._settings_scope is scope:
                    self._settings_scope = None
                    self._settings_service = None
                registrations = getattr(settings, "_registrations", None)
                if registrations is not None:
                    registrations.pop(SETTINGS_NAMESPACE, None)

            settings_ctx.effect(lambda: cleanup, "agentPresets.settings()")

        ctx.inject(["settings"], mount_settings)

        def agent_created(payload: Any) -> None:
            agent = payload.get("agent") if isinstance(payload, dict) else getattr(payload, "agent", None)
            if agent is None or not self.resolved_roots or self.composed_preset(agent.ctx) is not None:
                return
            logger = ctx.get("logger", None)
            if logger is not None and callable(getattr(logger, "warn", None)):
                logger.warn('agent "%s" was published without joining an agent preset' % agent.id)

        def session_event(session: Any, event: Any) -> None:
            event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
            if event_type != "agent-preset/selected":
                return
            data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
            ctx.emit("agent-preset/selected", session.id, data["agentPreset"])

        ctx.on("agent/created", agent_created)
        ctx.on("session/event", session_event)

    @property
    def default_id(self) -> str:
        if self._settings_scope is not None:
            value = self._settings_scope.get()
            if isinstance(value, dict) and value.get("default") is not None:
                return value["default"]
        return self.config.default

    defaultId = property(lambda self: self.default_id)

    @property
    def roots(self) -> List[PresetRoot]:
        return list(self.resolved_roots)

    @property
    def authorable(self) -> bool:
        return any(root.trust == "user" for root in self.resolved_roots)

    async def list(self) -> List[AgentPreset]:
        return discover_presets(self.resolved_roots)

    async def resolve(self, id_str: Optional[str] = None) -> AgentPreset:
        wanted = self.default_id if id_str is None else id_str
        presets = await self.list()
        for preset in presets:
            if preset.id == wanted:
                return preset
        raise UnknownPresetError(wanted, [preset.id for preset in presets])

    async def resolve_mountable(self, id_str: Optional[str] = None) -> AgentPreset:
        preset = await self.resolve(id_str)
        if preset.broken is not None:
            raise PresetMountError(preset.id, preset.broken)
        return preset

    async def _ensure_standing(self, preset: AgentPreset) -> _Standing:
        pending = self._standing.get(preset.id)
        if pending is not None:
            mounted = await pending
            current = _stamp(preset.path)
            if current is None or current == mounted.stamp:
                return mounted
            if self._standing.get(preset.id) is pending:
                self._standing.pop(preset.id, None)
            return await self._ensure_standing(preset)

        async def create() -> _Standing:
            stamp = _stamp(preset.path)
            if stamp is None:
                raise PresetMountError(preset.id, "composition file is unreadable: %s" % preset.path)
            scope_ctx = self.self_ctx.extend()
            mount = await mount_preset(scope_ctx, preset, self.self_ctx.get("loader"))
            return _Standing(mount, stamp)

        task = asyncio.ensure_future(create())
        self._standing[preset.id] = task
        try:
            return await task
        except BaseException:
            if self._standing.get(preset.id) is task:
                self._standing.pop(preset.id, None)
            raise

    def _bind(self, agent_ctx: Any, standing: _Standing) -> None:
        agent_ctx._parent = standing.mount.fiber.ctx
        agent_ctx._agent_preset_standing = standing.mount
        self._bindings[agent_ctx] = standing

    async def mount(self, agent_ctx: Any, id_str: Optional[str] = None) -> AgentPreset:
        if agent_ctx is self.self_ctx.root or getattr(agent_ctx, "_parent", None) is None:
            raise RuntimeError("agent-presets: refusing to compose an unscoped context")
        preset = await self.resolve_mountable(id_str)
        self._bind(agent_ctx, await self._ensure_standing(preset))
        return preset

    def compose_from(self, agent_ctx: Any, parent_ctx: Any) -> Optional[str]:
        if agent_ctx is self.self_ctx.root or getattr(agent_ctx, "_parent", None) is None:
            raise RuntimeError("agent-presets: refusing to compose an unscoped context")
        standing = self._bindings.get(parent_ctx)
        if standing is None:
            return None
        self._bind(agent_ctx, standing)
        return standing.mount.preset_id

    composeFrom = compose_from

    def composed_preset(self, agent_ctx: Any) -> Optional[str]:
        standing = self._bindings.get(agent_ctx)
        return standing.mount.preset_id if standing is not None else None

    composedPreset = composed_preset

    async def recompose(self, agent_ctx: Any, id_str: str) -> AgentPreset:
        if agent_ctx is self.self_ctx.root or getattr(agent_ctx, "_parent", None) is None:
            raise RuntimeError("agent-presets: refusing to recompose an unscoped context")
        preset = await self.resolve_mountable(id_str)
        self._bind(agent_ctx, await self._ensure_standing(preset))
        return preset

    async def standing_key_for(self, id_str: Optional[str] = None) -> Dict[str, str]:
        preset = await self.resolve_mountable(id_str)
        return (await self._ensure_standing(preset)).key

    standingKeyFor = standing_key_for

    def service_for(self, agent: Any, name: str) -> Any:
        return service_for_agent(self.self_ctx, agent, name)

    serviceFor = service_for

    async def read(self, id_str: str) -> str:
        return read_composition(await self.resolve(id_str))

    async def copy(self, from_id: str, id_str: str, name: Optional[str] = None) -> None:
        source = await self.resolve(from_id)
        if any(preset.id == id_str for preset in await self.list()):
            raise PresetExistsError(id_str)
        copy_composition(self.resolved_roots, source, id_str, name)
        self._standing.pop(id_str, None)

    async def remove(self, id_str: str) -> None:
        delete_composition(self.resolved_roots, await self.resolve(id_str))
        self._standing.pop(id_str, None)
        if self._settings_scope is None or self._settings_scope.get().get("default") != id_str:
            return
        result = self._settings_service.mutate(
            settings_namespace(SETTINGS_NAMESPACE), [{"op": "unset", "path": ["default"]}]
        )
        if inspect.isawaitable(result):
            await result
