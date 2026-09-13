"""
Shared profile boot for every dsh surface: resolve the profile, stack its
patch layers (bundle layers in dsh.profile.bundles order, the profile's
own cordis.patch.yml, --patch overlays, the telemetry switch), mount the
tree over the profile's empty root config, apply its selected patch-reload
lifecycle, and wire fail-loud plus bounded shutdown.

Matching reference/apps/cli/src/profile-boot.ts 1:1.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import copy
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.environment import resolve_dsh_home, DSH_LAUNCH_ENVIRONMENT_KEY, LaunchEnvironmentSnapshot
from dsh.boot.app_boot import (
    boot,
    install_fail_loud,
    load_optional_patches,
    load_overlay_patches,
    watch_user_patches,
)
from dsh.boot.profile import (
    load_profile,
    compose_entries,
    heal_profiles_module_fallback,
    PROFILE_PATCH_FILENAME,
    Profile,
)
from dsh.boot.cmdline import provide_cmdline, AppReady
from dsh.boot.process_shutdown import create_process_shutdown, ProcessShutdown

NAME = "dsh"

# Resolve INSTALL_ANCHOR
_CANDIDATE_ANCHORS = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "reference", "apps", "cli", "package.json")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "apps", "cli", "package.json")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "package.json")),
]
INSTALL_ANCHOR = _CANDIDATE_ANCHORS[0]
for _cand in _CANDIDATE_ANCHORS:
    if os.path.exists(_cand):
        INSTALL_ANCHOR = _cand
        break

TELEMETRY_ROW_ID = "session-telemetry-otel"

PROFILE_ROOT_CONFIG = """# dsh profile root — an empty entry list. The tree is composed as patches:
# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml, then any
# --patch overlays. Edit cordis.patch.yml, not this file.
[]
"""

PROFILE_ROOT_FILENAME = "cordis.yml"


class _AppReadyService(AppReady):
    def __init__(self):
        self._ready = False
        self._listeners: Set[Callable[[], None]] = set()

    def on_ready(self, listener: Callable[[], None]) -> Callable[[], None]:
        if self._ready:
            listener()
            return lambda: None
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    onReady = on_ready

    def _commit(self) -> None:
        if self._ready:
            return
        self._ready = True
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                pass
        self._listeners.clear()


def create_app_ready() -> Dict[str, Any]:
    svc = _AppReadyService()
    return {
        "service": svc,
        "commit": svc._commit,
    }


def home_patch_path(dsh_home: Optional[str] = None) -> str:
    """The home-level user patch layer ($DSH_HOME/cordis.patch.yml)."""
    home = dsh_home or resolve_dsh_home()
    return os.path.join(home, PROFILE_PATCH_FILENAME)


def resolve_telemetry_patch(disabled_env: Optional[str], has_row: bool) -> Optional[Dict[str, Any]]:
    """Resolve the telemetry opt-out switch into its boot patch."""
    if (disabled_env or "") == "" or not has_row:
        return None
    return {"id": TELEMETRY_ROW_ID, "disabled": True}


def prepare_profile(name: str, user_layer: bool = True, dsh_home: Optional[str] = None) -> Profile:
    """Load a resolved profile for `name` and rewrite the empty root config."""
    profile = load_profile(NAME, name, INSTALL_ANCHOR, home=dsh_home, options={"userLayer": user_layer})
    root_path = os.path.join(profile.dir, PROFILE_ROOT_FILENAME)
    try:
        with open(root_path, "w", encoding="utf-8") as f:
            f.write(PROFILE_ROOT_CONFIG)
    except Exception:
        pass
    return profile


class ComposedProfile:
    """One profile's patch layers, in application order."""

    def __init__(
        self,
        profile: Profile,
        bundle_patches: List[Dict[str, Any]],
        home_patches: List[Dict[str, Any]],
        overlays: List[Dict[str, Any]],
    ):
        self.profile = profile
        self.bundle_patches = bundle_patches
        self.bundlePatches = bundle_patches
        self.home_patches = home_patches
        self.homePatches = home_patches
        self.overlays = overlays

    def all_patches(self) -> List[Dict[str, Any]]:
        return [
            *self.bundle_patches,
            *self.profile.patches,
            *self.home_patches,
            *self.overlays,
        ]

    allPatches = all_patches


class SignalShutdown:
    """Invocation-level signal shutdown state matching TS AbortController."""

    def __init__(self):
        self.aborted = False

    def abort(self) -> None:
        self.aborted = True


def suppress_shutdown_error(ctx: Context, signal_obj: SignalShutdown, error: Any) -> None:
    """
    Re-throw a watcher-setup failure unless a shutdown already owns the tree.
    Matching TS suppressShutdownError.
    """
    if signal_obj.aborted:
        return
    if ctx.fiber.state != FiberState.ACTIVE or ctx.get("loader") is None:
        return
    raise error


async def compose_profile(
    name: str,
    patch_files: Sequence[str] = (),
    dsh_home: Optional[str] = None,
) -> ComposedProfile:
    """Load `name` and compose its effective patch stack."""
    profile = prepare_profile(name, dsh_home=dsh_home)
    await heal_profiles_module_fallback({"installAnchor": INSTALL_ANCHOR, "profile": profile})

    home_patches = load_optional_patches(NAME, home_patch_path(dsh_home)) or []
    overlays: List[Dict[str, Any]] = []
    for file in patch_files:
        overlays.extend(load_overlay_patches(NAME, os.path.abspath(file)))

    bundle_patches: List[Dict[str, Any]] = []
    for layer in profile.layers:
        bundle_patches.extend(layer.patches)

    composed_entries = compose_entries([bundle_patches, profile.patches, home_patches, overlays])
    has_telemetry = any(
        isinstance(row, dict) and row.get("id") == TELEMETRY_ROW_ID
        for row in composed_entries
    )

    composed_overlays = list(overlays)
    telemetry_patch = resolve_telemetry_patch(os.environ.get("DSH_TELEMETRY_DISABLED"), has_telemetry)
    if telemetry_patch is not None:
        composed_overlays.append(telemetry_patch)

    return ComposedProfile(
        profile=profile,
        bundle_patches=bundle_patches,
        home_patches=home_patches,
        overlays=composed_overlays,
    )


async def run_profile(options: Dict[str, Any]) -> Dict[str, Any]:
    """
    Boot one profile invocation end to end matching TS runProfile.
    """
    profile_name = options["profile"]
    patch_files = options.get("patchFiles", options.get("patch_files", []))
    dsh_home = options.get("dshHome", options.get("dsh_home"))
    environment = options.get("environment")
    if environment is None:
        from dsh.boot.app_boot import load_layered_env
        environment = load_layered_env(NAME)
    args = options.get("args", [])

    composed = await compose_profile(profile_name, patch_files, dsh_home=dsh_home)
    app: Dict[str, Any] = {"current": None}
    app_ready = create_app_ready()

    old_sigterm = None
    old_sigint = None

    async def _dispose_app():
        try:
            import signal
            if old_sigterm is not None:
                signal.signal(signal.SIGTERM, old_sigterm)
            if old_sigint is not None:
                signal.signal(signal.SIGINT, old_sigint)
        except (ValueError, OSError, AttributeError):
            pass
        curr = app.get("current")
        if curr is not None and hasattr(curr, "fiber"):
            await curr.fiber.dispose()
            # A script bridge can already own the root teardown; join it here so
            # the CLI exits only after the whole tree settled.
            await curr.fiber.await_settled()

    shutdown = create_process_shutdown(_dispose_app)
    signal_shutdown = SignalShutdown()

    def interrupt(code: int) -> None:
        signal_shutdown.abort()
        shutdown.interrupt(code)

    try:
        import signal
        old_sigterm = signal.signal(signal.SIGTERM, lambda s, f: interrupt(0))
        old_sigint = signal.signal(signal.SIGINT, lambda s, f: interrupt(130))
    except (ValueError, OSError, AttributeError):
        pass

    install_fail_loud(NAME, None, release=_dispose_app)

    root_config = os.path.join(composed.profile.dir, PROFILE_ROOT_FILENAME)

    def compose_live() -> List[Dict[str, Any]]:
        return copy.deepcopy([
            *composed.bundle_patches,
            *(load_optional_patches(NAME, composed.profile.patch_path) or []),
            *(load_optional_patches(NAME, home_patch_path()) or []),
            *composed.overlays,
        ])

    def host_setup(host_ctx: Context) -> None:
        app["current"] = host_ctx
        host_ctx.provide(DSH_LAUNCH_ENVIRONMENT_KEY, environment)
        provide_cmdline(host_ctx, {
            "args": args,
            "exit": lambda code: shutdown.shutdown(code),
            "ready": app_ready["service"],
        })

    all_patch_rows = copy.deepcopy(composed.all_patches())
    ctx = await boot(NAME, root_config, all_patch_rows, host_setup)
    app["current"] = ctx

    if (
        composed.profile.patch_reload == "live"
        and not signal_shutdown.aborted
        and ctx.fiber.state == FiberState.ACTIVE
        and ctx.get("loader") is not None
    ):
        try:
            if ctx.get("hmr") is None:
                if ctx.get("timer") is None:
                    await ctx.loader.create({"name": "@deepseek-ai/cordis-plugin-timer"})
                await ctx.loader.create({"name": "@deepseek-ai/cordis-plugin-hmr", "config": {"root": []}})
            await watch_user_patches(ctx, {
                "binName": NAME,
                "filename": composed.profile.patch_path,
                "compose": compose_live,
            })
            await watch_user_patches(ctx, {
                "binName": NAME,
                "filename": home_patch_path(),
                "compose": compose_live,
            })
        except Exception as error:
            suppress_shutdown_error(ctx, signal_shutdown, error)

    if (
        not signal_shutdown.aborted
        and ctx.fiber.state == FiberState.ACTIVE
        and ctx.get("loader") is not None
    ):
        app_ready["commit"]()

    wait_for_exit = options.get("wait_for_exit", options.get("waitForExit", True))
    if wait_for_exit:
        await shutdown.wait()

    return {"ctx": ctx, "shutdown": shutdown}


# CamelCase aliases
createAppReady = create_app_ready
homePatchPath = home_patch_path
resolveTelemetryPatch = resolve_telemetry_patch
prepareProfile = prepare_profile
composeProfile = compose_profile
runProfile = run_profile
