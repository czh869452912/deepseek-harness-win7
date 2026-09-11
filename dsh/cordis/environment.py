"""
Layered environment snapshot and secure .env discovery (`@deepseek-ai/dsh-launch-environment` & `@deepseek-ai/dsh-home-paths`).
Resolves inherited process environment, project-level `<cwd>/.env`, and user-level `$DSH_HOME/.env`
with security tripwires against bootstrap variable injection.
"""

import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


def expand_home_path(path: str) -> str:
    """Expand '~' or '~/' or '~\\' to the user home directory matching TS expandHomePath."""
    if path == "~":
        return os.path.expanduser("~")
    if path.startswith("~/") or path.startswith("~\\"):
        return os.path.join(os.path.expanduser("~"), path[2:])
    return path


DSH_HOME_DIR_NAME: str = ".dsh"
DEFAULT_DSH_HOME_DISPLAY: str = "~/.dsh"
DSH_HOME_ENV: str = "DSH_HOME"


def default_dsh_home() -> str:
    """Return default ~/.dsh path matching TS defaultDshHome."""
    return os.path.join(os.path.expanduser("~"), DSH_HOME_DIR_NAME)


def dsh_home_display(configured: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> str:
    """Return ~/.dsh or $DSH_HOME display string matching TS dshHomeDisplay."""
    resolved_home = resolve_dsh_home(configured, env)
    default_home = os.path.abspath(default_dsh_home())
    return DEFAULT_DSH_HOME_DISPLAY if os.path.normcase(resolved_home) == os.path.normcase(default_home) else "$DSH_HOME"


def canonicalize_watch_path(path: str) -> str:
    """Canonicalize a watch path with missing ancestor fallback matching TS canonicalizeWatchPath."""
    current = os.path.abspath(path)
    missing: List[str] = []
    while True:
        if os.path.exists(current):
            canonical = os.path.realpath(current)
            for seg in reversed(missing):
                canonical = os.path.join(canonical, seg)
            return canonical
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(path)
        missing.append(os.path.basename(current))
        current = parent


def resolve_dsh_home(custom_home: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> str:
    """
    Resolve the Harness home directory ($DSH_HOME or ~/.dsh), expanding ~ if present.
    Matching reference/packages/util/home-paths/src/index.ts:87-91.
    """
    if custom_home is not None:
        selected = custom_home
    else:
        env_dict = env if isinstance(env, dict) else os.environ
        env_home = env_dict.get(DSH_HOME_ENV)
        if env_home is not None and env_home.strip():
            selected = env_home
        else:
            selected = default_dsh_home()
    return os.path.abspath(expand_home_path(selected))


# Exact variable names that cannot be set by discovered .env files
BOOTSTRAP_NAMES: Set[str] = {
    # Process launch and runtime resolution
    "PATH", "HOME", "USERPROFILE", "SHELL",
    "NODE_OPTIONS", "NODE_PATH", "NODE_EXTRA_CA_CERTS",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    # Interpreter startup hooks
    "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS",
    "PERL5OPT", "PERL5LIB", "PYTHONSTARTUP", "PYTHONPATH", "PYTHONHOME",
    "RUBYOPT", "RUBYLIB", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS",
    # Version control hooks, editors, pagers
    "GIT_SSH", "GIT_SSH_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR",
    "GIT_ASKPASS", "SSH_ASKPASS",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT",
    "EDITOR", "VISUAL", "PAGER", "BROWSER",
    # Network reach and trust
    "DEEPSEEK_BASE_URL", "DEEPSEEK_SEARCH_BASE_URL",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "NODE_TLS_REJECT_UNAUTHORIZED",
}

# Prefix patterns forbidden in .env files
BOOTSTRAP_PREFIXES: Tuple[str, ...] = ("DSH_", "XDG_", "DYLD_", "BASH_FUNC_")


def is_bootstrap_only(name: str) -> bool:
    """
    Whether a variable may come ONLY from the inherited launch environment.
    """
    upper = name.upper()
    if upper in BOOTSTRAP_NAMES:
        return True
    for prefix in BOOTSTRAP_PREFIXES:
        if upper.startswith(prefix):
            return True
    return False


def parse_dotenv(content: str) -> Dict[str, str]:
    """
    Parse dotenv formatted text safely into key-value pairs.
    Supports multiline quoted values, inline comments, and single-pass double-quote unescaping.
    """
    entries: Dict[str, str] = {}
    lines = content.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        raw_line = lines[i]
        line = raw_line.strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") and len(line) > 7:
            line = line[7:].strip()

        if "=" not in line:
            continue

        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue

        if val.startswith('"'):
            # Double-quoted (may be multiline)
            collected = [val[1:]]
            closed = False
            cur = collected[0]
            if len(cur) >= 1 and cur.endswith('"') and not cur.endswith('\\"'):
                collected[0] = cur[:-1]
                closed = True
            while not closed and i < n:
                next_line = lines[i]
                i += 1
                if next_line.endswith('"') and not next_line.endswith('\\"'):
                    collected.append(next_line[:-1])
                    closed = True
                else:
                    collected.append(next_line)
            combined = "\n".join(collected)
            esc_map = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
            entries[key] = re.sub(r'\\([\\ntr"])', lambda m: esc_map.get(m.group(1), m.group(0)), combined)
        elif val.startswith("'"):
            # Single-quoted (literal, may be multiline)
            collected = [val[1:]]
            closed = False
            cur = collected[0]
            if len(cur) >= 1 and cur.endswith("'"):
                collected[0] = cur[:-1]
                closed = True
            while not closed and i < n:
                next_line = lines[i]
                i += 1
                if next_line.endswith("'"):
                    collected.append(next_line[:-1])
                    closed = True
                else:
                    collected.append(next_line)
            entries[key] = "\n".join(collected)
        else:
            # Unquoted: strip inline comment after whitespace
            val_clean = re.split(r'\s+#', val, maxsplit=1)[0].strip()
            entries[key] = val_clean

    return entries


class LaunchEnvironmentEntry:
    """A resolved environment variable entry with its origin source layer."""

    def __init__(self, value: str, source: str, path: Optional[str] = None):
        self.value = value
        self.source = source  # 'process', 'project-env', 'user-env'
        self.path = path

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"value": self.value, "source": self.source}
        if self.path is not None:
            res["path"] = self.path
        return res


SOURCE_ORDER: List[str] = ["process", "project-env", "user-env"]


class LaunchEnvironmentSnapshot:
    """
    Immutable snapshot of layered environment sources.
    """

    def __init__(self, layers: List[Dict[str, Any]]):
        self._raw_layers = layers
        self._layers: Dict[str, Dict[str, str]] = {}
        self._paths: Dict[str, str] = {}

        for layer in layers:
            src = layer["source"]
            vals = dict(layer.get("values", {}))
            folded: Dict[str, str] = {}
            for k, v in vals.items():
                lookup_key = k.upper() if sys.platform == "win32" else k
                folded[lookup_key] = v
            self._layers[src] = folded
            if "path" in layer and layer["path"]:
                self._paths[src] = layer["path"]

    @property
    def layers(self) -> List[Dict[str, Any]]:
        return self._raw_layers

    def get_from(self, name: str, sources: Optional[List[str]] = None) -> Optional[LaunchEnvironmentEntry]:
        lookup = name.upper() if sys.platform == "win32" else name
        allowed = SOURCE_ORDER if sources is None else list(sources)
        for src in SOURCE_ORDER:
            if src not in allowed:
                continue
            if src in self._layers and lookup in self._layers[src]:
                val = self._layers[src][lookup]
                p = self._paths.get(src)
                return LaunchEnvironmentEntry(value=val, source=src, path=p)
        return None

    def get(self, name: str) -> Optional[LaunchEnvironmentEntry]:
        return self.get_from(name, SOURCE_ORDER)

    def get_value(self, name: str, default: Optional[str] = None) -> Optional[str]:
        entry = self.get(name)
        return entry.value if entry else default


LAUNCH_ENVIRONMENT_KEY: str = "launchEnvironment"
DSH_LAUNCH_ENVIRONMENT_KEY: str = LAUNCH_ENVIRONMENT_KEY


def launch_environment_of(ctx: Any) -> LaunchEnvironmentSnapshot:
    """
    Get the launch environment snapshot from context, falling back to process-only snapshot matching TS launchEnvironmentOf.
    """
    if hasattr(ctx, "get"):
        res = ctx.get(LAUNCH_ENVIRONMENT_KEY)
        if res is not None:
            return res
    return LaunchEnvironmentSnapshot([{"source": "process", "values": dict(os.environ)}])


def read_env_layer(bin_name: str, dir_path: str) -> Optional[Dict[str, Any]]:
    """
    Read and validate a single directory's .env file.
    Delegates to dsh.boot.app_boot._read_env_layer.
    """
    from dsh.boot.app_boot import _read_env_layer
    return _read_env_layer(bin_name, dir_path)


def load_layered_env(
    bin_name: str = "dsh",
    cwd: Optional[str] = None,
    custom_home: Optional[str] = None,
    warn: Optional[Callable[[str], None]] = None,
) -> LaunchEnvironmentSnapshot:
    """
    Discover and load layered environment snapshot.
    Delegates to canonical implementation in dsh.boot.app_boot.load_layered_env.
    """
    from dsh.boot.app_boot import load_layered_env as _boot_load_layered_env
    boot_snapshot = _boot_load_layered_env(bin_name=bin_name, cwd=cwd, warn=warn, home=custom_home)
    return LaunchEnvironmentSnapshot(boot_snapshot.layers)


def resolve_layered_config(
    ctx: Any,
    namespace: str,
    key: str,
    system_default: Any = None,
    preset_override: Any = None,
    cli_env_value: Any = None,
    workspace_value: Any = None,
) -> Any:
    """
    Configuration chain loading order (lowest to highest precedence):
    1. System Defaults
    2. Home Settings (~/.dsh/settings.yaml)
    3. Workspace Config
    4. Preset Overrides
    5. CLI / Env (Wins)
    """
    val = system_default

    # 2. Home Settings (~/.dsh/settings.yaml)
    if ctx and hasattr(ctx, "has") and ctx.has("settings"):
        settings_svc = ctx.get("settings")
        if hasattr(settings_svc, "get_setting"):
            home_val = settings_svc.get_setting(namespace, key)
            if home_val is not None:
                val = home_val

    # 3. Workspace Config
    if workspace_value is not None:
        val = workspace_value

    # 4. Preset Overrides
    if preset_override is not None:
        val = preset_override

    # 5. CLI / Env (Highest precedence)
    if cli_env_value is not None:
        val = cli_env_value

    return val

