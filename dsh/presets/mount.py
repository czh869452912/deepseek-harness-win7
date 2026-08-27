"""Standing preset composition mounts backed by the Cordis Loader entry machinery."""

import asyncio
import copy
import os
from typing import Any, Dict, List, Optional

import yaml

from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import Loader
from dsh.cordis.loader_tree import EntryTree
from dsh.presets.preset import AgentPreset, PresetMountError


class PresetMount:
    def __init__(self, preset_id: str, fiber: Any, key: Dict[str, str], tree: Any):
        self.preset_id = preset_id
        self.presetId = preset_id
        self.fiber = fiber
        self.key = key
        self.tree = tree


_mounts: List[PresetMount] = []


def _within_fiber(fiber: Any, root: Any) -> bool:
    current = fiber
    while current is not None:
        if current is root:
            return True
        parent_ctx = getattr(current, "parent", None)
        parent = getattr(parent_ctx, "fiber", None)
        if parent is current:
            return False
        current = parent
    return False


def live_preset_mounts() -> List[PresetMount]:
    _mounts[:] = [mount for mount in _mounts if getattr(mount.fiber, "uid", None) is not None]
    return list(_mounts)


def leaked_services(ctx: Any, mount_fiber: Any) -> List[str]:
    leaked = []
    for key, impl in list(ctx.reflect.store.items()):
        if key != getattr(impl, "name", None):
            continue
        if _within_fiber(getattr(impl, "fiber", None), mount_fiber):
            leaked.append(impl.name)
    return sorted(set(leaked))


def standing_mount_for(agent_ctx: Any) -> Optional[PresetMount]:
    standing = getattr(agent_ctx, "_agent_preset_standing", None)
    if standing is None or getattr(standing.fiber, "uid", None) is None:
        return None
    return standing


def service_for_agent(ctx: Any, agent: Any, name: str) -> Any:
    agent_ctx = getattr(agent, "ctx", None)
    mount = standing_mount_for(agent_ctx)
    if mount is None:
        return None
    for impl in list(ctx.reflect.store.values()):
        if getattr(impl, "name", None) != name:
            continue
        if _within_fiber(getattr(impl, "fiber", None), mount.fiber):
            return impl.value
    return None


def inactive_rows(tree: Any) -> List[str]:
    lines = []
    for entry in tree.entries():
        if entry.disabled:
            continue
        fiber = entry.fiber
        if fiber is None:
            lines.append("%s (%s): never started" % (entry.options.get("id"), entry.options.get("name")))
            continue
        missing = [name for name in fiber.inject if fiber.ctx.get(name, None) is None]
        if missing:
            lines.append("%s (%s): waiting for %s" % (
                entry.options.get("id"), entry.options.get("name"), ", ".join(missing)))
    return lines


class _PresetTree(EntryTree):
    def __init__(self, ctx: Any, host_loader: Loader, composition_path: str):
        super().__init__(ctx)
        self.owner_ctx = ctx
        self.host_loader = host_loader
        self.isolation = host_loader.isolation
        self.builtins = host_loader.builtins
        self.composition_path = composition_path

    def import_plugin(self, name: str) -> Any:
        if os.path.isabs(name):
            return self.host_loader.import_plugin(name)
        if name.startswith("."):
            resolved = os.path.abspath(os.path.join(os.path.dirname(self.composition_path), name))
            return self.host_loader.import_plugin(resolved)
        return self.host_loader.import_plugin(name)

    import_ = import_plugin

    def get_tasks(self) -> List[Any]:
        tasks = []
        for entry in self.entries():
            task = entry._init_task or (
                entry.fiber.inertia if entry.fiber is not None else None
            )
            if task is not None:
                tasks.append(task)
        return tasks

    getTasks = get_tasks

    def is_js_expr(self, value: Any) -> bool:
        return self.host_loader.is_js_expr(value)

    def evaluate(self, ctx: Any, expression: str) -> Any:
        return self.host_loader.evaluate(ctx, expression)

    def interpolate(self, ctx: Any, value: Any) -> Any:
        return self.host_loader.interpolate(ctx, value)

    def write(self) -> None:
        return None


def _load_rows(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        rows = yaml.load(handle, Loader=yaml.SafeLoader)
    if not isinstance(rows, list):
        raise TypeError("composition must be a list")
    return copy.deepcopy(rows)


async def mount_preset(agent_ctx: Any, preset: AgentPreset, host_loader: Optional[Loader] = None) -> PresetMount:
    if agent_ctx is None or getattr(agent_ctx, "_parent", None) is None:
        raise RuntimeError(
            'agent-presets: refusing to mount preset "%s" into an unscoped context; '
            "its registrations would apply to every agent in the process" % preset.id
        )
    loader = host_loader or agent_ctx.get("loader", None)
    if loader is None:
        raise RuntimeError("agent-presets: loader service is required")

    def standing_plugin(_ctx: Any) -> None:
        return None

    fiber = agent_ctx.registry.plugin(standing_plugin, {}, parent_ctx=agent_ctx)
    await fiber
    tree = _PresetTree(fiber.ctx, loader, preset.path)
    try:
        Loader._legacy_load(tree, _load_rows(preset.path), fiber.ctx)
        await asyncio.sleep(0)
        while tree.get_tasks():
            outcomes = await asyncio.gather(*tree.get_tasks(), return_exceptions=True)
            failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            if failures:
                raise failures[0]
        for entry in tree.entries():
            if entry.fiber is not None and entry.fiber.state == FiberState.ACTIVE:
                await entry.fiber
            elif entry.fiber is not None and entry.fiber.state == FiberState.FAILED:
                await entry.fiber
        unusable = inactive_rows(tree)
        if unusable:
            raise RuntimeError("%d row(s) did not activate:\n%s" % (len(unusable), "\n".join(unusable)))
        leaked = leaked_services(agent_ctx, fiber)
        if leaked:
            raise RuntimeError(
                "row(s) published process-global service(s) [%s]; a preset service must sit "
                "behind an isolate realm or move to the host composition" % ", ".join(leaked)
            )
        mount = PresetMount(preset.id, fiber, {"agentPreset": preset.id}, tree)
        _mounts.append(mount)
        return mount
    except BaseException as error:
        await fiber.dispose()
        detail = str(error)
        raise PresetMountError(preset.id, "%s (%s)" % (detail, preset.path), cause=error)


mountPreset = mount_preset
livePresetMounts = live_preset_mounts
leakedServices = leaked_services
inactiveRows = inactive_rows
standingMountFor = standing_mount_for
serviceForAgent = service_for_agent
