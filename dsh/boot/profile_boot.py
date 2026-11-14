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
import asyncio
import os
import json
import shutil
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
    PROFILE_TEMPLATES,
    resolve_profile_dir,
    init_profile,
    report_skipped_bundles,
)
from dsh.boot.cmdline import provide_cmdline, AppReady
from dsh.boot.process_shutdown import create_process_shutdown, ProcessShutdown

NAME = "dsh"

# Resolve INSTALL_ANCHOR
_CANDIDATE_ANCHORS = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "apps", "cli", "package.json")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "package.json")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "reference", "apps", "cli", "package.json")),
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


def initialize_profile_from_default(name, from_default_profile, home=None):
    """Exclusively claim a new profile, copying only shipped template metadata."""
    profiles_root = os.path.abspath(os.path.join(home or resolve_dsh_home(), 'profiles'))
    directory = os.path.abspath(resolve_profile_dir(name, home))
    if os.path.dirname(directory) != profiles_root or os.path.basename(directory) != name:
        raise ValueError('dsh: invalid profile initialization target')
    template = PROFILE_TEMPLATES.get(from_default_profile)
    if template is None:
        expected = ', '.join(json.dumps(value, ensure_ascii=False) for value in sorted(PROFILE_TEMPLATES))
        raise RuntimeError('dsh: unknown default profile %s; expected one of %s' % (json.dumps(from_default_profile, ensure_ascii=False), expected))
    if name in PROFILE_TEMPLATES:
        raise RuntimeError('dsh: profile %s is shipped and cannot be a custom profile target; omit --from-default-profile to use it' % json.dumps(name, ensure_ascii=False))
    os.makedirs(os.path.dirname(directory), exist_ok=True)
    try:
        os.mkdir(directory)
    except FileExistsError:
        manifest = os.path.join(directory, 'package.json')
        if os.path.exists(manifest):
            raise RuntimeError('dsh: profile %s already exists at %s; omit --from-default-profile to use it' % (json.dumps(name, ensure_ascii=False), manifest))
        raise RuntimeError('dsh: profile directory %s already exists; choose an unused profile name' % directory)
    try:
        init_profile(directory, template['bundles'], template['patchReload'])
    except BaseException as error:
        # Only the exact directory exclusively claimed above is removable.
        if os.path.dirname(os.path.abspath(directory)) != profiles_root or os.path.basename(directory) != name:
            raise RuntimeError('profile cleanup target changed') from error
        try:
            shutil.rmtree(directory)
        except BaseException as cleanup_error:
            aggregate = RuntimeError('dsh: profile initialization failed and %s could not be removed' % directory)
            aggregate.errors = [error, cleanup_error]
            raise aggregate from error
        raise


def prepare_profile(name: str, user_layer: bool = True, dsh_home: Optional[str] = None, from_default_profile=None) -> Profile:
    """Load a resolved profile for `name` and rewrite the empty root config."""
    if from_default_profile is not None:
        initialize_profile_from_default(name, from_default_profile, dsh_home)
    profile = load_profile(NAME, name, INSTALL_ANCHOR, home=dsh_home, options={"userLayer": user_layer})
    report_skipped_bundles(NAME, profile)
    root_path = os.path.join(profile.dir, PROFILE_ROOT_FILENAME)
    with open(root_path, "w", encoding="utf-8") as f:
        f.write(PROFILE_ROOT_CONFIG)
    return profile


def admit_historical_persona_patches(rows):
    """Translate the two retired persona keys at the profile input boundary.

    Keep on-disk user patches and unrelated plugin configuration untouched.
    Explicit current keys win, including an explicitly empty prefix.
    """
    rows = copy.deepcopy(rows)

    def visit(entries):
        if not isinstance(entries, list):
            return
        for row in entries:
            if not isinstance(row, dict):
                continue
            name, identity = row.get('name'), row.get('id')
            config = row.get('config')
            if isinstance(config, dict):
                if name == '@deepseek-ai/dsh-system-prompt' or name is None and identity == 'system-prompt':
                    if 'persona' in config:
                        config.setdefault('personaPrefix', config.pop('persona'))
                elif name == '@deepseek-ai/dsh-persona' or name is None and identity == 'persona':
                    if 'text' in config:
                        config.setdefault('prefix', config.pop('text'))
            visit(row.get('insert'))
            # Cordis group configuration is itself a list of entry patches.
            if isinstance(config, list):
                visit(config)

    visit(rows)
    return rows


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
        return admit_historical_persona_patches([
            *self.bundle_patches,
            *self.profile.patches,
            *self.home_patches,
            *self.overlays,
        ])

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
    from_default_profile=None,
) -> ComposedProfile:
    """Load `name` and compose its effective patch stack."""
    profile = prepare_profile(name, dsh_home=dsh_home, from_default_profile=from_default_profile)
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


async def _run_profile(options: Dict[str, Any]) -> Dict[str, Any]:
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

    from dsh.host.http_proxy import install_proxy_from_environment
    dispose_proxy = await install_proxy_from_environment(environment, lambda message: sys.stderr.write(NAME + ': ' + message + '\n'))
    holder = options.get('_python_profile_context')
    if holder is not None:
        holder['dispose_proxy'] = dispose_proxy
    try:
        composed = await compose_profile(profile_name, patch_files, dsh_home=dsh_home)
    except BaseException:
        await dispose_proxy()
        raise
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
        try:
            curr = app.get("current")
            if curr is not None and hasattr(curr, "fiber"):
                await curr.serial('app/stopping')
                await curr.fiber.dispose()
                # A script bridge can already own the root teardown; join it here so
                # the CLI exits only after the whole tree settled.
                await curr.fiber.await_settled()
        finally:
            await dispose_proxy()

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

    from dsh.boot.session_compatibility import preserve_default_session_encoding

    def compose_live() -> List[Dict[str, Any]]:
        return preserve_default_session_encoding(admit_historical_persona_patches([
            *composed.bundle_patches,
            *(load_optional_patches(NAME, composed.profile.patch_path) or []),
            *(load_optional_patches(NAME, home_patch_path()) or []),
            *composed.overlays,
        ]), dsh_home)

    def host_setup(host_ctx: Context) -> None:
        app["current"] = host_ctx
        holder = options.get("_python_profile_context")
        if holder is not None:
            holder["ctx"] = host_ctx
        lease = options.get("_python_profile_lease")
        if lease is not None:
            dependencies = options.get('_python_dependency_lease')
            def close_leases():
                try:
                    if dependencies is not None:
                        dependencies.close()
                finally:
                    lease.close()
            def release_after_shutdown():
                import asyncio
                settlement = getattr(host_ctx.fiber, "_disposal_task", None)
                if settlement is not None:
                    settlement.add_done_callback(lambda _: close_leases())
                else:
                    async def release():
                        try:
                            await host_ctx.fiber.await_settled()
                        finally:
                            close_leases()
                    # Keep this observer outside the fiber's settlement set.
                    asyncio.get_running_loop().create_task(release())

            host_ctx.disposable(release_after_shutdown, "python-profile-lease")
        host_ctx.provide(DSH_LAUNCH_ENVIRONMENT_KEY, environment)
        host_ctx.provide('profileContext', {
            'name': composed.profile.name, 'dir': composed.profile.dir,
            'patchPath': composed.profile.patch_path, 'installAnchor': INSTALL_ANCHOR,
            'cwd': os.getcwd(), 'home': os.path.abspath(dsh_home or resolve_dsh_home()),
            'startedBundles': [layer.package_name for layer in composed.profile.layers],
            'overlays': copy.deepcopy(composed.overlays),
            'telemetryDisabledEnv': os.environ.get('DSH_TELEMETRY_DISABLED'),
        })
        provide_cmdline(host_ctx, {
            "args": args,
            "exit": lambda code: shutdown.shutdown(code),
            "ready": app_ready["service"],
        })

    all_patch_rows = await asyncio.get_running_loop().run_in_executor(
        None, preserve_default_session_encoding, copy.deepcopy(composed.all_patches()), dsh_home)
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


async def run_profile(options: Dict[str, Any]) -> Dict[str, Any]:
    from dsh.boot.profile import resolve_profile_dir
    from dsh.boot.profile_lease import ProfileLease
    from dsh.boot.python_plugins import JOURNAL, recover

    home = options.get("dshHome", options.get("dsh_home"))
    if options.get('fromDefaultProfile') is not None:
        initialize_profile_from_default(options['profile'], options['fromDefaultProfile'], home)
    directory = resolve_profile_dir(options["profile"], home)
    if os.path.isfile(os.path.join(directory, JOURNAL)):
        with ProfileLease(directory, exclusive=True):
            recover(directory)
    lease = ProfileLease(directory)
    dependencies = None
    holder: Dict[str, Any] = {}
    try:
        from dsh.boot.python_plugin_dependencies import PythonDependencyLease
        dependencies = PythonDependencyLease(directory)
        result = await _run_profile(dict(options, _python_profile_lease=lease, _python_dependency_lease=dependencies, _python_profile_context=holder))
        return result
    except BaseException:
        try:
            ctx = holder.get("ctx")
            if ctx is not None:
                await ctx.fiber.dispose()
                await ctx.fiber.await_settled()
        finally:
            try:
                if holder.get('dispose_proxy') is not None:
                    await holder['dispose_proxy']()
            finally:
                try:
                    if dependencies is not None:
                        dependencies.close()
                finally:
                    lease.close()
        raise


# CamelCase aliases
createAppReady = create_app_ready
homePatchPath = home_patch_path
resolveTelemetryPatch = resolve_telemetry_patch
prepareProfile = prepare_profile
initializeProfileFromDefault = initialize_profile_from_default
composeProfile = compose_profile
runProfile = run_profile
