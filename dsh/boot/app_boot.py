"""
Boot and configuration orchestration matching reference/packages/boot/app-boot.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import asyncio
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse
from urllib.request import url2pathname
import weakref
import yaml

from dsh.cordis.context import Context
from dsh.cordis.environment import (
    BOOTSTRAP_NAMES,
    BOOTSTRAP_PREFIXES,
    is_bootstrap_only,
    parse_dotenv,
    resolve_dsh_home,
)
from dsh.cordis.file_lock import with_file_lock
from dsh.cordis.fiber import FiberState
from dsh.cordis.include import ConfigFileError, Include
from dsh.cordis.loader import Entry, EntryGroup, Group, Loader, apply_entry_patches, evaluate_expr, is_js_expr, js_constructor, resolve_module_specifier


from dsh.boot.profile import (
    PROFILES_DIR,
    PROFILE_PATCH_FILENAME,
    PROFILE_MODULE_FALLBACK_DIR,
    PROFILE_TEMPLATES,
    DEFAULT_PROFILE_BUNDLES,
    DEFAULT_PROFILE_PATCH_RELOAD,
    INSTALLATION_OWNED_PROFILE_TUPLES,
    ProfileLayer,
    Profile,
    resolve_profile_dir,
    resolveProfileDir,
    init_profile,
    initProfile,
    read_profile_manifest,
    readProfileManifest,
    write_profile_manifest,
    writeProfileManifest,
    resolve_bundle_dir,
    resolveBundleDir,
    load_profile,
    loadProfile,
    compose_entries,
    composeEntries,
    heal_profiles_module_fallback,
    healProfilesModuleFallback,
)

HARNESS_SOURCE_SECTION = "harness:source"
FAIL_LOUD_RELEASE_TIMEOUT_MS = 2000


def path_to_file_url(path: str) -> str:
    return Path(os.path.abspath(path)).as_uri()


def file_url_to_path(url: str) -> str:
    if url.startswith("file://"):
        parsed = urlparse(url)
        return url2pathname(parsed.path)
    return url


def resolve_config_path(
    config_path: str,
    snapshot_mode: Optional[str] = None,
    cwd: Optional[str] = None,
) -> str:
    """Resolve the config to boot. Replay swaps a cordis.yml basename for cordis.snapshot.yml."""
    base_cwd = cwd or os.getcwd()
    absolute = os.path.abspath(os.path.join(base_cwd, config_path))
    if snapshot_mode != "replay":
        return absolute
    dir_name = os.path.dirname(absolute)
    base_name = os.path.basename(absolute)
    replay_name = re.sub(r"cordis\.ya?ml$", "cordis.snapshot.yml", base_name)
    return os.path.join(dir_name, replay_name)


def load_env(
    bin_name: str,
    target_dir: Optional[str] = None,
    warn: Optional[Callable[[str], None]] = None,
) -> None:
    """Load optional .env from target_dir into os.environ."""
    base_dir = target_dir or os.getcwd()
    env_path = os.path.join(base_dir, ".env")
    if not os.path.exists(env_path):
        return
    if os.path.isdir(env_path):
        msg = f"{bin_name}: failed to load .env: [Errno 21] Is a directory: '{env_path}'\n"
        if warn:
            warn(msg)
        else:
            sys.stderr.write(msg)
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
        parsed = parse_dotenv(content)
        for k, v in parsed.items():
            if k not in os.environ:
                os.environ[k] = v
    except Exception as e:
        msg = f"{bin_name}: failed to load .env: {e}\n"
        if warn:
            warn(msg)
        else:
            sys.stderr.write(msg)


class LaunchEnvironmentSnapshot:
    """Snapshot of layered environment tracking provenance."""

    def __init__(self, layers: List[Dict[str, Any]]):
        self._layers = layers

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        for layer in reversed(self._layers):
            if name in layer["values"]:
                res = {"value": layer["values"][name], "source": layer["source"]}
                if "path" in layer:
                    res["path"] = layer["path"]
                return res
        return None

    def get_from(self, name: str, sources: List[str]) -> Optional[Dict[str, Any]]:
        for layer in reversed(self._layers):
            if layer["source"] in sources and name in layer["values"]:
                res = {"value": layer["values"][name], "source": layer["source"]}
                if "path" in layer:
                    res["path"] = layer["path"]
                return res
        return None

    # camelCase alias
    getFrom = get_from


def _read_env_layer(
    bin_name: str,
    target_dir: str,
    warn: Optional[Callable[[str], None]] = None,
) -> Optional[Dict[str, Any]]:
    path = os.path.join(os.path.abspath(target_dir), ".env")
    if not os.path.exists(path):
        return None
    if os.path.isdir(path):
        msg = f"{bin_name}: failed to load .env: [Errno 21] Is a directory: '{path}'\n"
        if warn:
            warn(msg)
        else:
            sys.stderr.write(msg)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        msg = f"{bin_name}: failed to load .env: {e}\n"
        if warn:
            warn(msg)
        else:
            sys.stderr.write(msg)
        return None

    values = parse_dotenv(content)
    for name in values.keys():
        if is_bootstrap_only(name):
            raise RuntimeError(
                f'{bin_name}: {path} sets "{name}", which only the launching environment may set '
                f"(it decides how this process starts, where its code and instructions load from, or how it reaches the network); "
                f"export {name} instead of putting it in a .env file"
            )
    return {"path": path, "values": values}


def load_layered_env(
    bin_name: str,
    cwd: Optional[str] = None,
    warn: Optional[Callable[[str], None]] = None,
) -> LaunchEnvironmentSnapshot:
    """Load inherited > cwd/.env > $DSH_HOME/.env environment snapshot."""
    home = resolve_dsh_home()
    base_cwd = os.path.abspath(cwd or os.getcwd())
    inherited = dict(os.environ)

    project_layer = _read_env_layer(bin_name, base_cwd, warn)
    user_layer = None if home == base_cwd else _read_env_layer(bin_name, home, warn)

    for layer in (project_layer, user_layer):
        if layer is not None:
            for name, value in layer["values"].items():
                if name not in os.environ:
                    os.environ[name] = value

    layers = [{"source": "process", "values": inherited}]
    if project_layer is not None:
        layers.append({"source": "project-env", "path": project_layer["path"], "values": project_layer["values"]})
    if user_layer is not None:
        layers.append({"source": "user-env", "path": user_layer["path"], "values": user_layer["values"]})

    return LaunchEnvironmentSnapshot(layers)


def _anchor_inserted_plugin_names(patches: List[Dict[str, Any]], filepath: str) -> List[Dict[str, Any]]:
    base_dir = os.path.dirname(os.path.abspath(filepath))

    def visit(entry: Dict[str, Any]) -> None:
        name = entry.get("name")
        if isinstance(name, str) and (name.startswith("./") or name.startswith("../")):
            abs_plugin = os.path.abspath(os.path.join(base_dir, name))
            entry["name"] = path_to_file_url(abs_plugin)
        if entry.get("group") and isinstance(entry.get("config"), list):
            for child in entry["config"]:
                if isinstance(child, dict):
                    visit(child)

    for patch in patches:
        inserts = patch.get("insert")
        if isinstance(inserts, list):
            for item in inserts:
                if isinstance(item, dict):
                    visit(item)
    return patches


def _parse_patch_list(bin_name: str, filepath: str, content: str, label: str) -> List[Dict[str, Any]]:
    try:
        parsed = yaml.safe_load(content)
    except Exception as e:
        raise RuntimeError(f"{bin_name}: failed to parse {label} {filepath}: {e}")
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise RuntimeError(f"{bin_name}: {label} {filepath} must be a top-level YAML array of loader patch entries")
    for index, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise RuntimeError(f"{bin_name}: {label} entry {index + 1} in {filepath} must be a mapping (a loader patch entry)")
    return _anchor_inserted_plugin_names(parsed, filepath)


def load_optional_patches(bin_name: str, filepath: str) -> Optional[List[Dict[str, Any]]]:
    """Load an optional patch-list file; returns None if file does not exist."""
    if not os.path.exists(filepath):
        return None
    if os.path.isdir(filepath):
        raise RuntimeError(f"{bin_name}: failed to read patches {filepath}: Is a directory")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        raise RuntimeError(f"{bin_name}: failed to read patches {filepath}: {e}")
    return _parse_patch_list(bin_name, filepath, content, "patches")


def load_overlay_patches(bin_name: str, filepath: str) -> List[Dict[str, Any]]:
    """Load a required overlay patch list; throws if file does not exist."""
    if not os.path.exists(filepath) or os.path.isdir(filepath):
        raise RuntimeError(f"{bin_name}: failed to read overlay {filepath}: file not found or is a directory")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        raise RuntimeError(f"{bin_name}: failed to read overlay {filepath}: {e}")
    return _parse_patch_list(bin_name, filepath, content, "overlay")


def render_config_dump(
    bin_name: str,
    absolute_config_path: str,
    layers: List[Dict[str, Any]],
    warn: Optional[Callable[[str], None]] = None,
) -> str:
    """Render offline configuration composition with layer provenance comments matching TS renderConfigDump."""
    if not os.path.exists(absolute_config_path):
        raise RuntimeError(f"{bin_name}: failed to read config {absolute_config_path}: file not found")
    try:
        with open(absolute_config_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        raise RuntimeError(f"{bin_name}: failed to read config {absolute_config_path}: {e}")

    try:
        parsed = yaml.safe_load(content)
    except Exception as e:
        raise RuntimeError(f"{bin_name}: failed to parse config {absolute_config_path}: {e}")

    if not isinstance(parsed, list):
        raise RuntimeError(f"{bin_name}: config {absolute_config_path} must be a top-level YAML array of entries")

    base_label = os.path.basename(absolute_config_path)
    base = parsed

    def format_msg(msg: str, args: Tuple[Any, ...]) -> str:
        idx = 0
        def repl(match):
            nonlocal idx
            val = args[idx] if idx < len(args) else ""
            idx += 1
            return json.dumps(val)
        return re.sub(r"%C", repl, msg)

    def snapshot(count: int, warnings: List[str]) -> List[Dict[str, Any]]:
        flattened = copy.deepcopy([p for layer in layers[:count] for p in layer.get("patches", [])])
        return apply_entry_patches(
            base,
            flattened,
            warn=lambda msg, *args: warnings.append(format_msg(msg, args)),
        )

    previous = base
    previous_warnings: List[str] = []
    provenance: List[Dict[str, Any]] = [{"origin": base_label, "patchedBy": []} for _ in base]
    composed = base

    for count in range(1, len(layers) + 1):
        layer = layers[count - 1]
        warnings: List[str] = []
        composed = snapshot(count, warnings)
        for line in warnings[len(previous_warnings):]:
            warn_line = f"{bin_name}: [{layer['label']}] {line}"
            if warn:
                warn(warn_line)
            else:
                sys.stderr.write(f"{warn_line}\n")

        before = [json.dumps(e, sort_keys=True) for e in previous]
        for index in range(len(composed)):
            if index >= len(before):
                provenance.append({"origin": layer["label"], "patchedBy": []})
            elif json.dumps(composed[index], sort_keys=True) != before[index]:
                if layer["label"] not in provenance[index]["patchedBy"]:
                    provenance[index]["patchedBy"].append(layer["label"])

        previous = composed
        previous_warnings = warnings

    # Group dump
    lines: List[str] = []
    current_label: Optional[str] = None
    group: List[Any] = []

    def flush():
        nonlocal current_label, group
        if current_label is None or not group:
            return
        lines.append(f"# == {current_label}")
        dumped = yaml.safe_dump(group, sort_keys=False, allow_unicode=True).rstrip()
        lines.append(dumped)
        group = []

    for index in range(len(composed)):
        rec = provenance[index]
        if not rec["patchedBy"]:
            label = rec["origin"]
        else:
            label = f"{rec['origin']}, patched by {', '.join(rec['patchedBy'])}"
        if label != current_label:
            flush()
            current_label = label
        group.append(composed[index])
    flush()

    return "\n".join(lines) + "\n"


_bootstrap_includes: Any = weakref.WeakKeyDictionary()


async def mount_root_include(
    ctx: Context,
    absolute_config_path: str,
    patches: Optional[List[Dict[str, Any]]] = None,
    bare_module_base_url: Optional[str] = None,
) -> Optional[Entry]:
    """Mount the exact root Include entry used by app boot."""
    loader = ctx.get("loader")
    if loader is None:
        return None

    if bare_module_base_url is None:
        loader.builtins["include"] = Include
        loader.registry_map["cordis:include"] = Include
        loader.registry_map["@deepseek-ai/cordis-plugin-include"] = Include
    else:
        class HostBoundInclude(Include):
            def import_plugin(self, name: str, get_outer_stack: Optional[Callable[[], List[str]]] = None) -> Any:
                specifier = path_to_file_url(name) if os.path.isabs(name) else name
                if name.startswith(".") or name.startswith("cordis:"):
                    return super().import_plugin(specifier, get_outer_stack)
                base_path = file_url_to_path(bare_module_base_url)
                base_dir = os.path.dirname(base_path) if os.path.isfile(base_path) or bare_module_base_url.endswith(".mjs") or bare_module_base_url.endswith(".js") else base_path
                resolved = resolve_module_specifier(name, base_dir)
                if resolved and os.path.exists(resolved):
                    return super().import_plugin(resolved, get_outer_stack)
                return super().import_plugin(specifier, get_outer_stack)

        loader.builtins["include"] = HostBoundInclude
        loader.registry_map["cordis:include"] = HostBoundInclude
        loader.registry_map["@deepseek-ai/cordis-plugin-include"] = HostBoundInclude

    loader.builtins["group"] = Group

    include_config: Dict[str, Any] = {
        "path": path_to_file_url(absolute_config_path),
    }
    if patches:
        include_config["patches"] = list(patches)

    root_include = {
        "id": "include",
        "name": "cordis:include",
        "config": include_config,
    }
    include_id = await loader.create(root_include)
    entry = loader.resolve(include_id)
    if entry is not None:
        _bootstrap_includes[ctx] = entry
    return entry


_assembled_activation_rejections: Dict[Any, int] = {}


def retain_assembled_rejection(reason: Any) -> None:
    _assembled_activation_rejections[reason] = _assembled_activation_rejections.get(reason, 0) + 1


def release_assembled_rejection(reason: Any) -> None:
    count = _assembled_activation_rejections.get(reason)
    if count is None or count <= 1:
        _assembled_activation_rejections.pop(reason, None)
    else:
        _assembled_activation_rejections[reason] = count - 1


def install_fail_loud(
    bin_name: str,
    proc: Any = None,
    release: Optional[Callable[[], Any]] = None,
) -> Callable[[], None]:
    """Install uncaught rejection/exception guard."""
    exiting = False

    class DefaultProc:
        def on(self, event, handler): pass
        def off(self, event, handler): pass
        class stderr:
            @staticmethod
            def write(s): sys.stderr.write(s)
        @staticmethod
        def exit(code): sys.exit(code)

    process_target = proc if proc is not None else DefaultProc()

    def handler(err: Any):
        nonlocal exiting
        if err in _assembled_activation_rejections:
            return
        if exiting:
            return
        exiting = True
        err_msg = getattr(err, "stack", None) or (str(err) if err else "error")
        process_target.stderr.write(f"{bin_name}: fatal load failure: {err_msg}\n")
        if release is None:
            process_target.exit(1)
            return

        async def run_release():
            try:
                res = release()
                if asyncio.iscoroutine(res):
                    await asyncio.wait_for(res, timeout=FAIL_LOUD_RELEASE_TIMEOUT_MS / 1000.0)
            except Exception:
                pass
            process_target.exit(1)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(run_release())
            else:
                loop.run_until_complete(run_release())
        except Exception:
            process_target.exit(1)

    process_target.on("unhandledRejection", handler)

    loop = None
    orig_loop_handler = None
    if proc is None:
        try:
            loop = asyncio.get_event_loop()
            orig_loop_handler = loop.get_exception_handler()

            def _loop_exc_handler(l: Any, context: Dict[str, Any]) -> None:
                exc = context.get("exception") or context.get("message")
                handler(exc)
                if orig_loop_handler:
                    orig_loop_handler(l, context)
                else:
                    l.default_exception_handler(context)

            loop.set_exception_handler(_loop_exc_handler)
        except Exception:
            pass

    def uninstall():
        process_target.off("unhandledRejection", handler)
        if loop and not loop.is_closed():
            try:
                loop.set_exception_handler(orig_loop_handler)
            except Exception:
                pass

    return uninstall


def assert_entries_loaded(ctx: Context, bin_name: str) -> None:
    """Ensure all non-disabled entries have fibers."""
    loader = ctx.get("loader")
    if not loader:
        return
    failed = [entry for entry in loader.entries() if entry.fiber is None and not getattr(entry, "disabled", False)]
    if failed:
        names = ", ".join(entry.options.get("name", getattr(entry, "name", "unknown")) for entry in failed)
        raise RuntimeError(
            f"{bin_name}: plugin(s) failed to load: {names}; Cordis startup failed because these plugin(s) could not be resolved (see the error(s) logged above)"
        )


def _format_activation_error(error: Any) -> str:
    if isinstance(error, Exception):
        return getattr(error, "stack", None) or str(error)
    return str(error)


async def assert_entries_activated(ctx: Context, bin_name: str) -> None:
    """Ensure all entries are active and settled."""
    assert_entries_loaded(ctx, bin_name)
    loader = ctx.get("loader")
    if not loader:
        return

    failures: List[str] = []
    rejection_reasons: List[Any] = []

    for entry in loader.entries():
        fiber = entry.fiber
        if fiber is None or getattr(entry, "disabled", False):
            continue
        state = fiber.state
        if state == FiberState.ACTIVE:
            continue
        if state == FiberState.FAILED:
            try:
                await_fn = getattr(fiber, "await_", None) or getattr(fiber, "await", None)
                if await_fn:
                    await await_fn()
            except Exception as error:
                rejection_reasons.append(error)
                failures.append(f"{entry.options.get('name', getattr(entry, 'name', 'unknown'))}: {_format_activation_error(error)}")
            continue
        if state == FiberState.PENDING:
            missing = [s for s in getattr(fiber, "inject", {}) if getattr(fiber.ctx, "get", lambda _: None)(s) is None]
            subject = "service" if len(missing) == 1 else "services"
            missing_names = ", ".join(missing) if missing else "unknown"
            failures.append(f"{entry.options.get('name', getattr(entry, 'name', 'unknown'))}: pending (waiting for {subject}: {missing_names})")
        else:
            failures.append(f"{entry.options.get('name', getattr(entry, 'name', 'unknown'))}: fiber state {state}")

    if failures:
        for reason in rejection_reasons:
            retain_assembled_rejection(reason)
        try:
            await asyncio.sleep(0)
        finally:
            for reason in rejection_reasons:
                release_assembled_rejection(reason)
        noun = "entry" if len(failures) == 1 else "entries"
        raise RuntimeError(f"{bin_name}: {len(failures)} {noun} did not activate\n" + "\n".join(failures))


async def boot(
    bin_name: str,
    absolute_config_path: str,
    patches: Optional[List[Dict[str, Any]]] = None,
    prepare: Optional[Callable[[Context], Any]] = None,
    bare_module_base_url: Optional[str] = None,
) -> Context:
    """Boot the Loader against absolute_config_path and return when settled."""
    ctx = Context()
    stage = "host preparation failed"
    try:
        ctx.base_url = path_to_file_url(os.path.dirname(absolute_config_path)) + "/"
        ctx.provide("dshHomePath", lambda sub="": os.path.join(resolve_dsh_home(), sub) if sub else resolve_dsh_home())
        await ctx.plugin(Loader)
        if prepare:
            res = prepare(ctx)
            if asyncio.iscoroutine(res):
                await res
        stage = "plugin tree failed to load"
        await mount_root_include(ctx, absolute_config_path, patches, bare_module_base_url)
        loader = ctx.get("loader")
        if loader is not None:
            await_fn = getattr(loader, "await_", None) or getattr(loader, "await", None)
            if await_fn:
                await await_fn()
        if ctx.get("loader") is None:
            return ctx
        await assert_entries_activated(ctx, bin_name)
        return ctx
    except Exception as cause:
        if hasattr(ctx, "fiber") and hasattr(ctx.fiber, "dispose"):
            await ctx.fiber.dispose()
        detail = str(cause)
        deepest: Any = cause
        while getattr(deepest, "__cause__", None) is not None or getattr(deepest, "cause", None) is not None:
            deepest = getattr(deepest, "__cause__", None) or getattr(deepest, "cause", None)

        if hasattr(deepest, "errors") and isinstance(getattr(deepest, "errors", None), (list, tuple)):
            header = getattr(deepest, "stack", None) or str(deepest)
            body = "\n".join(_format_activation_error(e) for e in deepest.errors)
            stack = f"\n{header}\n{body}"
        elif deepest is not cause:
            stack = f"\n{getattr(deepest, 'stack', None) or str(deepest)}"
        else:
            stack = ""
        raise RuntimeError(f"{bin_name}: {stage}: {detail}{stack}") from cause


async def watch_user_patches(ctx: Context, options: Dict[str, Any]) -> Callable[[], Any]:
    """Watch user patch layer through HMR and reapply."""
    bin_name = options.get("binName", "dsh")
    filename = options.get("filename", "")
    compose = options.get("compose", lambda patches: patches)

    hmr = ctx.get("hmr")
    if hmr is None:
        raise RuntimeError(f"{bin_name}: user patch-layer watching requires the Cordis HMR service")
    entry = _bootstrap_includes.get(ctx)
    if entry is None:
        raise RuntimeError(f"{bin_name}: user patch-layer watching requires the root Include entry")

    async def on_change():
        cfg = dict(entry.options.get("config", {}))
        cfg.pop("patches", None)
        user_patches = load_optional_patches(bin_name, filename) or []
        patches = compose(user_patches)
        await entry.update({"config": dict(cfg, patches=patches)})

    try:
        disposer = await hmr.register_config(filename, on_change)
        return disposer
    except Exception as error:
        if getattr(error, "code", None) == "INACTIVE_EFFECT" or "inactive" in str(error).lower():
            async def noop_disposer(): pass
            return noop_disposer
        raise


def add_harness_source_section(ctx: Context, source_root: str) -> Optional[Callable[[], None]]:
    """Add harness source checkout section to system prompt."""
    system_prompt = ctx.get("systemPrompt") or ctx.get("system_prompt")
    if system_prompt is None or not hasattr(system_prompt, "section"):
        return None
    return system_prompt.section({
        "name": HARNESS_SOURCE_SECTION,
        "order": -900,
        "text": (
            f"The DeepSeek Harness implementation checkout is at {source_root}. "
            f"The checkout location and current working directory are separate values and may differ; "
            f"never infer the working directory from this path. Use pwd to determine the current working directory. "
            f"Use this checkout only to inspect or extend DSH itself."
        ),
    })


# CamelCase aliases for TS parity
renderConfigDump = render_config_dump
loadOverlayPatches = load_overlay_patches
loadOptionalPatches = load_optional_patches
resolveConfigPath = resolve_config_path
loadEnv = load_env
loadLayeredEnv = load_layered_env
assertEntriesLoaded = assert_entries_loaded
assertEntriesActivated = assert_entries_activated
mountRootInclude = mount_root_include
installFailLoud = install_fail_loud
watchUserPatches = watch_user_patches
addHarnessSourceSection = add_harness_source_section
